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


def _det_hash(*args: object) -> int:
    """Deterministic hash for use in seeded output paths.

    Python's builtin :func:`hash` on strings is salted per-interpreter (see
    ``PYTHONHASHSEED``), so two runs of the same clinosim invocation produce
    different lot numbers. P1-7 (session 46) uncovered this via the
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


def generate_immunizations(
    patient, schedule: dict, as_of: date, rng: np.random.Generator, nurse_ids: list[str] | None = None
) -> list:
    from clinosim.types.encounter import ImmunizationRecord

    dob = getattr(patient, "date_of_birth", None)
    base_age = int(getattr(patient, "age", 0) or 0)
    sex = getattr(patient, "sex", "M") or "M"
    pid = getattr(patient, "patient_id", "") or ""
    # RM-3 (session 42): pick a stable "family nurse" per patient (nurses
    # administer routine vaccinations in JP practice).
    default_nurse = ""
    if nurse_ids:
        default_nurse = nurse_ids[sum(ord(c) for c in pid) % len(nurse_ids)]
    out: list = []
    # C1-19 (session 41 cycle 1): a small share of vaccines are documented in
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

        # C3-03 continuation (session 43): synthetic lot number generator.
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
        # P1-7 (session 46): use _det_hash (sha256-based) instead of the
        # Python builtin `hash()`. Builtin hash on strings is salted per
        # interpreter run so lot numbers used to vary between two runs at
        # the same seed. reproduce.sh gates this now.
        _mfr_hash = f"{(_det_hash(cvx) % 900 + 100):03d}"  # 100-999

        def _synthetic_lot(occurrence):
            batch = f"{(_det_hash(cvx, occurrence.year, occurrence.month) % 900 + 100):03d}"
            return f"L{_mfr_hash}-{occurrence.year:04d}{occurrence.month:02d}-{batch}"

        if freq == "annual":
            month = int(v.get("season_month", 10))
            for yr in range(start.year, as_of.year + 1):
                occ = date(yr, month, 1)
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
                elif rng.random() < 0.02:
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
                elif rng.random() < 0.02:
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
