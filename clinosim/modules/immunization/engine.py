"""Immunization history generation (AD-55 Base).

Pure functions deriving a patient's adult vaccine history from demographics and a
locale schedule (eligibility age, availability date, season, age/sex coverage).
Codes (CVX) live in clinosim.codes; schedules in clinosim/locale/<country>/.
"""

from __future__ import annotations

import hashlib
from datetime import date
from functools import lru_cache
from pathlib import Path

import numpy as np
import yaml

from clinosim.modules._shared import is_jp, is_us

# ---------------------------------------------------------------------------
# Immunization event recording (Issue #637)
# ---------------------------------------------------------------------------

IMMUNIZATION_NOT_DONE_RECORDING_RATE: float = 0.02
"""Per-scheduled-dose probability of emitting a
``status="not-done"`` ImmunizationRecord when the coverage draw
fails. Represents the explicit-refusal / deferral rate that clinics
DO document, distinct from silent no-shows.

Empirical tuning for the synthetic simulator: 2% matches the
observed inpatient / clinic documentation rate for declined
vaccinations. Firing rate does not depend on freq (annual /
every-n-years / once); the value is shared across all three
scheduling branches."""


def _det_hash(*args: object) -> int:
    """Deterministic hash for use in seeded output paths.

    Python's builtin :func:`hash` on strings is salted per-interpreter (see
    ``PYTHONHASHSEED``), so two runs of the same clinosim invocation produce
    different lot numbers. P1-7 uncovered this via the
    reproduce.sh determinism gate — the immunization ``lotNumber`` was the
    only field in the whole FHIR bundle that varied across runs at a fixed
    seed. This helper substitutes ``hashlib.sha256`` so the value is
    reproducible.
    """
    key = repr(args).encode("utf-8")
    return int(hashlib.sha256(key).hexdigest(), 16)


_HERE = Path(__file__).resolve().parent
_LOCALE = _HERE.parents[1] / "locale"


@lru_cache(maxsize=2)
def load_schedule(country: str) -> dict:
    """Load the immunization schedule for ``country``. Returns ``{}`` for
    unsupported countries (only US/JP data exists) rather than silently
    falling back to US data (locale-loader unsupported-country contract,
    2026-07-02 grand design review)."""
    if not (is_us(country) or is_jp(country)):
        return {}
    key = "jp" if is_jp(country) else "us"
    with open(_LOCALE / key / "immunization_schedule.yaml") as f:
        return (yaml.safe_load(f) or {}).get("vaccines", {})


def _age_on(dob: date | None, on: date, fallback_age: int) -> int:
    if dob is None:
        return fallback_age
    return on.year - dob.year - ((on.month, on.day) < (dob.month, dob.day))


def _coverage(cov: dict, age: int, sex: str) -> float:
    for band, ms in cov.items():
        lo, hi = (int(x) for x in band.split("-"))
        if lo <= age <= hi:
            return float(ms.get(sex, next(iter(ms.values()))))
    return 0.0


def _parse(d: str) -> date:
    y, m, day = (int(x) for x in d.split("-"))
    return date(y, m, day)


def _safe_date(year: int, month: int, day: int) -> date:
    """Construct a date, clamping Feb 29 to Feb 28 in non-leap years."""
    try:
        return date(year, month, day)
    except ValueError:
        return date(year, month, day - 1)


# Issue #921: flu seasons span calendar year boundaries. Months whose integer
# value is >= _SEASON_ANCHOR_MONTH belong to the season-start calendar year;
# months < _SEASON_ANCHOR_MONTH roll into the following calendar year.
# 6 (June) safely separates the northern-hemisphere flu season (Sep-Feb) from
# its opposite off-season half, so months 6..12 anchor to season_yr and 1..5
# roll to season_yr+1. Both US and JP flu seasons stay well inside those halves.
_SEASON_ANCHOR_MONTH = 6


def _band_lookup(bands: dict, age: int) -> float:
    """Look up an age-banded numeric value ("18-49" -> 0.4). Returns 0.0 when
    ``bands`` is falsy or the age falls outside every band. Used by both
    coverage_by_age_sex (with a sex-dimension nested) and wave epoch age_weight
    (flat)."""
    if not bands:
        return 0.0
    for band, val in bands.items():
        lo, hi = (int(x) for x in band.split("-"))
        if lo <= age <= hi:
            return float(val)
    return 0.0


def _pick_flu_month(
    seasonal_dist: dict[str, float],
    season_yr: int,
    start: date,
    as_of: date,
    rng: np.random.Generator,
) -> date | None:
    """Sample a (year, month) for a flu dose in the flu season anchored at
    season_yr. Returns a date-of-month-1 or None if no configured month falls
    within [start, as_of]. See :data:`_SEASON_ANCHOR_MONTH` for the wrap rule.

    Weights are relative — normalized across the surviving candidates so a
    partly-clipped season still samples from a proper distribution.
    """
    candidates: list[tuple[int, int]] = []
    weights: list[float] = []
    for m_str, w in seasonal_dist.items():
        m = int(m_str)
        yr = season_yr if m >= _SEASON_ANCHOR_MONTH else season_yr + 1
        first = date(yr, m, 1)
        last = _safe_date(yr, m, 28)
        # month is eligible if any day inside it overlaps [start, as_of]
        if last < start or first > as_of:
            continue
        candidates.append((yr, m))
        weights.append(float(w))
    if not candidates:
        return None
    total = sum(weights)
    if total <= 0:
        return None
    probs = [w / total for w in weights]
    idx = int(rng.choice(len(candidates), p=probs))
    yr, m = candidates[idx]
    return date(yr, m, 1)


def _pick_wave_epoch_date(
    wave_epochs: list[dict],
    start: date,
    as_of: date,
    age_at: int,
    rng: np.random.Generator,
) -> date | None:
    """Sample a date for a once-in-a-lifetime vaccine following a wave-epoch
    model. Two-stage sampling:

    1. Pick an epoch weighted by ``age_weight[band]``, filtered to epochs whose
       window intersects [start, as_of].
    2. Within the sampled epoch enumerate every (year, month) that has a
       positive ``monthly_curve`` weight AND overlaps the clipped window; pick
       one weighted by curve, then pick a day uniformly inside the valid range
       of that month.

    Returns None if no epoch survives filtering (patient window falls entirely
    outside every epoch, or every eligible epoch has zero age_weight for this
    band). Callers should skip emission in that case rather than fall through.
    """
    # Stage 1: epoch selection.
    epoch_choices: list[tuple[dict, date, date]] = []
    epoch_weights: list[float] = []
    for epoch in wave_epochs:
        e_start = _parse(epoch["start"])
        e_end = _parse(epoch["end"])
        w_start = max(e_start, start)
        w_end = min(e_end, as_of)
        if w_start > w_end:
            continue
        w = _band_lookup(epoch.get("age_weight", {}), age_at)
        if w <= 0:
            continue
        epoch_choices.append((epoch, w_start, w_end))
        epoch_weights.append(w)
    if not epoch_choices:
        return None
    total = sum(epoch_weights)
    probs = [w / total for w in epoch_weights]
    idx = int(rng.choice(len(epoch_choices), p=probs))
    epoch, w_start, w_end = epoch_choices[idx]

    # Stage 2: (year, month) within the clipped epoch window.
    curve = epoch.get("monthly_curve", {}) or {}
    ym_candidates: list[tuple[date, date]] = []
    ym_weights: list[float] = []
    y, m = w_start.year, w_start.month
    end_y, end_m = w_end.year, w_end.month
    while (y, m) <= (end_y, end_m):
        w = float(curve.get(str(m), 0.0))
        if w > 0:
            first_valid = max(date(y, m, 1), w_start)
            last_valid = min(_safe_date(y, m, 28), w_end)
            if first_valid <= last_valid:
                ym_candidates.append((first_valid, last_valid))
                ym_weights.append(w)
        m += 1
        if m == 13:
            m = 1
            y += 1
    if not ym_candidates:
        # No configured month falls within the clipped window; fall back to
        # uniform placement across the whole window rather than dropping the
        # dose (an epoch was picked so the patient IS being vaccinated).
        span = (w_end - w_start).days
        offset = int(rng.integers(0, span + 1)) if span > 0 else 0
        return date.fromordinal(w_start.toordinal() + offset)
    total = sum(ym_weights)
    probs = [w / total for w in ym_weights]
    idx = int(rng.choice(len(ym_candidates), p=probs))
    first_valid, last_valid = ym_candidates[idx]
    day = int(rng.integers(first_valid.day, last_valid.day + 1))
    return date(first_valid.year, first_valid.month, day)


def generate_immunizations(
    patient, schedule: dict, as_of: date, rng: np.random.Generator, nurse_ids: list[str] | None = None
) -> list:
    from clinosim.types.encounter import ImmunizationRecord

    dob = getattr(patient, "date_of_birth", None)
    base_age = int(getattr(patient, "age", 0) or 0)
    sex = getattr(patient, "sex", "M") or "M"
    pid = getattr(patient, "patient_id", "") or ""
    # RM-3: pick a stable "family nurse" per patient (nurses
    # administer routine vaccinations in JP practice).
    default_nurse = ""
    if nurse_ids:
        default_nurse = nurse_ids[sum(ord(c) for c in pid) % len(nurse_ids)]
    out: list = []
    # C1-19: a small share of vaccines are documented in
    # the EHR as declined by the patient / caregiver (FHIR status="not-done" +
    # statusReason "PATOBJ" patient objection). Real JP EHRs carry this ~1-3%
    # depending on vaccine — flu/pneumococcal in the elderly; HPV in
    # adolescents. Sampled per schedule entry via the same rng stream.

    for _name, v in schedule.items():
        cvx = str(v["cvx"])
        min_age = int(v["min_age"])
        avail = _parse(v["available_from"])
        freq = v["frequency"]
        cov = v["coverage_by_age_sex"]

        # earliest eligible date = max(availability, date patient reached min_age)
        reached: date | None
        if dob is not None:
            reached = _safe_date(dob.year + min_age, dob.month, dob.day)
        else:
            reached = date(as_of.year - (base_age - min_age), 1, 1) if base_age >= min_age else None
        if reached is None:
            continue
        start = max(avail, reached)
        # Optional EHR data-retention window: only keep the last `history_years`
        # of history (real EHRs don't carry decades of e.g. annual flu shots).
        history_years = v.get("history_years")
        if history_years is not None:
            lookback = _safe_date(as_of.year - int(history_years), as_of.month, as_of.day)
            start = max(start, lookback)
        if start > as_of:
            continue

        # C3-03 continuation: synthetic lot number generator.
        # JP 薬機法 requires vaccine lot tracking for post-market surveillance
        # (副作用報告制度). Real lot numbers come from manufacturer QC systems;
        # for synthetic data we generate a deterministic manufacturer-style
        # tag: <MFR>-<YYYYMM>-<BATCH> where MFR is derived from CVX code
        # (deterministic 3-letter tag) and BATCH is a 3-digit patient-relative
        # sequence. The result is NOT an authoritative lot number — it is a
        # structural placeholder that satisfies FHIR Immunization.lotNumber
        # 0..1 and JP practice pattern documentation. Downstream consumers
        # must treat it as synthetic (AD-57 spirit: no fabrication of billing
        # / regulatory codes; lot number is neither).
        # P1-7: use _det_hash (sha256-based) instead of the
        # Python builtin `hash()`. Builtin hash on strings is salted per
        # interpreter run so lot numbers used to vary between two runs at
        # the same seed. reproduce.sh gates this now.
        _mfr_hash = f"{(_det_hash(cvx) % 900 + 100):03d}"  # 100-999

        def _synthetic_lot(occurrence):
            batch = f"{(_det_hash(cvx, occurrence.year, occurrence.month) % 900 + 100):03d}"
            return f"L{_mfr_hash}-{occurrence.year:04d}{occurrence.month:02d}-{batch}"

        if freq == "annual":
            # Issue #921: prefer per-season seasonal_distribution (yaml-driven)
            # over a single fixed season_month. Iterate season anchor years
            # covering [start, as_of], where a "season year N" corresponds to
            # Oct(N)-Feb(N+1). start.year-1 handles patients whose eligibility
            # window opens in Jan/Feb of the year (they can still take the
            # tail end of the prior season). as_of.year+1 handles doses that
            # roll to Jan/Feb after the season anchor, then get filtered
            # against as_of by _pick_flu_month.
            seasonal_dist = v.get("seasonal_distribution") or {}
            default_month = int(v.get("season_month", 10))
            if seasonal_dist:
                season_years = range(start.year - 1, as_of.year + 1)
            else:
                season_years = range(start.year, as_of.year + 1)
            for yr in season_years:
                if seasonal_dist:
                    occ = _pick_flu_month(seasonal_dist, yr, start, as_of, rng)
                    if occ is None:
                        continue
                else:
                    occ = date(yr, default_month, 1)
                    if occ < start or occ > as_of:
                        continue
                age_at = _age_on(dob, occ, base_age)
                if rng.random() < _coverage(cov, age_at, sex):
                    out.append(
                        ImmunizationRecord(
                            vaccine_cvx=cvx,
                            occurrence_date=occ,
                            administered_by=default_nurse,
                            lot_number=_synthetic_lot(occ),
                        )
                    )
                elif rng.random() < IMMUNIZATION_NOT_DONE_RECORDING_RATE:
                    out.append(
                        ImmunizationRecord(
                            vaccine_cvx=cvx,
                            occurrence_date=occ,
                            status="not-done",
                        )
                    )
        elif freq == "every_n_years":
            interval = int(v.get("interval_years", 10))
            yr = start.year
            while _safe_date(yr, start.month, start.day) <= as_of:
                occ = _safe_date(yr, start.month, start.day)
                age_at = _age_on(dob, occ, base_age)
                if rng.random() < _coverage(cov, age_at, sex):
                    out.append(
                        ImmunizationRecord(
                            vaccine_cvx=cvx,
                            occurrence_date=occ,
                            administered_by=default_nurse,
                            lot_number=_synthetic_lot(occ),
                        )
                    )
                elif rng.random() < IMMUNIZATION_NOT_DONE_RECORDING_RATE:
                    out.append(
                        ImmunizationRecord(
                            vaccine_cvx=cvx,
                            occurrence_date=occ,
                            status="not-done",
                        )
                    )
                yr += interval
        else:  # once
            age_at = _age_on(dob, as_of, base_age)
            if rng.random() < _coverage(cov, age_at, sex):
                # Issue #921: prefer wave_epochs (real-world timeline of the
                # program) over a uniform draw across the whole span. Falls
                # back to uniform when yaml declares no epochs (e.g. PPSV23).
                wave_epochs = v.get("wave_epochs")
                if wave_epochs:
                    occ = _pick_wave_epoch_date(wave_epochs, start, as_of, age_at, rng)
                    if occ is None:
                        continue
                else:
                    # place once at a deterministic point within [start, as_of]
                    span = (as_of - start).days
                    offset = int(rng.integers(0, span + 1)) if span > 0 else 0
                    occ = date.fromordinal(start.toordinal() + offset)
                out.append(
                    ImmunizationRecord(
                        vaccine_cvx=cvx,
                        occurrence_date=occ,
                        administered_by=default_nurse,
                        lot_number=_synthetic_lot(occ),
                    )
                )

    out.sort(key=lambda r: r.occurrence_date)
    return out
