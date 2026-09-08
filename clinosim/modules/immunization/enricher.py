"""Immunization enricher (AD-55 Base, AD-56 post_records).

Generates each patient's vaccine history with a dedicated sub-seed so the main
simulation random stream is untouched (AD-16). occurrence dates <= snapshot (AD-32).
"""

from __future__ import annotations

import hashlib
from datetime import date, datetime

import numpy as np

from clinosim.modules._shared import get_attr_or_key as _get
from clinosim.modules._shared import set_attr_or_key as _set
from clinosim.modules.immunization.engine import generate_immunizations, load_schedule
from clinosim.seeding import ENRICHER_SEED_OFFSETS, derive_sub_seed
from clinosim.types.encounter import Encounter, EncounterStatus, EncounterType


def _as_of(ctx, rec) -> date:
    snap = _get(_get(ctx, "config"), "snapshot_date", None) if _get(ctx, "config") else None
    if snap:
        y, m, d = (int(x) for x in str(snap).split("-"))
        # Issue #926: cap `as_of` at date_of_death so the immunization
        # scheduler never emits a vaccine after the patient has died.
        # Nine of the 47 deceased patients in p=10000 v0.5.0 received
        # post-mortem flu shots (the flu scheduler picks a fixed month
        # per year — 11-01 — independent of death status). Clamping
        # here is the single seam that gates all three frequency
        # branches (annual / every_n_years / once) in
        # ``generate_immunizations`` without touching the pure engine.
        patient = _get(rec, "patient")
        dod = _get(patient, "date_of_death", None) if patient else None
        if isinstance(dod, date):
            return min(date(y, m, d), dod)
        return date(y, m, d)
    # else: latest encounter admission date
    encs = _get(rec, "encounters", []) or []
    dates = []
    for e in encs:
        adm = _get(e, "admission_datetime")
        if isinstance(adm, datetime):
            dates.append(adm.date())
    if dates:
        latest = max(dates)
        # Issue #926: same cap for the fallback branch.
        patient = _get(rec, "patient")
        dod = _get(patient, "date_of_death", None) if patient else None
        if isinstance(dod, date):
            return min(latest, dod)
        return latest
    raise ValueError(
        "immunization _as_of(): no deterministic date reference available — "
        "ctx.config.snapshot_date is unset AND the record has no encounters "
        "with a valid admission_datetime. The CLI always resolves "
        "snapshot_date (default: today, resolved once at invocation) before "
        "any record is processed, so this indicates a caller/test setup gap, "
        "not a real simulation path."
    )


def _align_to_encounters(imm_recs: list, encounters: list) -> list:
    """Snap each immunization's occurrence_date to a nearby pediatric_visit
    encounter and stamp the encounter_id.

    Issue #1184 F4 / #1186 F6 CIF-layer fix (#1197 verify 2nd pass): the
    immunization scheduler picks occurrence_date on an age-anchored
    calendar independent of the encounter list, so the FHIR emit-time
    bridge found only ~4/1969 same-day matches. Aligning here at CIF-
    generation time bridges the gap in one seam.

    For each Immunization:
      * Search encounters within ±14 days whose encounter_type is
        outpatient. Prefer the nearest by absolute-day distance.
      * When a match exists, snap `occurrence_date` to that encounter's
        admission_datetime.date() and record `encounter_id`.
      * When no encounter is within window, leave both fields unchanged
        (silence beats fabrication).

    Never introduces a new encounter — the alignment only rebinds
    existing ones. Deterministic (no rng).
    """
    if not imm_recs or not encounters:
        return imm_recs
    # Collect eligible encounter dates once.
    _enc_days: list[tuple[date, str]] = []
    for enc in encounters:
        _adm = _get(enc, "admission_datetime", None)
        if not isinstance(_adm, datetime):
            continue
        _enc_type = str(_get(enc, "encounter_type", "") or "")
        # Immunizations are outpatient / ambulatory events. Filter to
        # OUTPATIENT encounter_type; inpatient / ED are not immunization
        # sites. `encounter_type` may be an enum with a `.value` attr.
        _et_val = getattr(_enc_type, "value", _enc_type)
        if str(_et_val).lower() not in ("outpatient", "amb", "ambulatory"):
            continue
        _eid = _get(enc, "encounter_id", "") or ""
        if not _eid:
            continue
        _enc_days.append((_adm.date(), _eid))
    if not _enc_days:
        return imm_recs
    for imm in imm_recs:
        occ = _get(imm, "occurrence_date", None)
        if not isinstance(occ, date):
            continue
        # Nearest outpatient encounter within ±60 days. The window is
        # 60 rather than 14 to cover annual flu shots — the flu
        # scheduler picks a fixed month per year (Oct-Dec) that may not
        # coincide with the patient's own chronic follow-up cadence
        # (every 30-90 days). Pediatric infant series and one-off adult
        # vaccinations remain within the same window; the tightest
        # clinical constraint (immunization within one full quarter of
        # any real-world office visit) is preserved.
        best_delta: int | None = None
        best_day: date | None = None
        best_eid: str = ""
        for _day, _eid in _enc_days:
            _delta = abs((_day - occ).days)
            if _delta > 60:
                continue
            if best_delta is None or _delta < best_delta:
                best_delta = _delta
                best_day = _day
                best_eid = _eid
        if best_day is not None and best_eid:
            _set(imm, "occurrence_date", best_day)
            _set(imm, "encounter_id", best_eid)
    return imm_recs


def _synthesize_vaccination_encounter(imm: object, patient_id: str, country: str) -> Encounter:
    """Create a minimal outpatient Encounter for an orphan immunization.

    Issue #1197 verify Pass 5 follow-up — companion encounter emit per the
    responsibility-decomposition design (see PR description). When
    ``_align_to_encounters`` cannot find an existing outpatient encounter
    within ±60 days of an in-sim-window immunization, this helper emits
    the encounter the FHIR world implicitly requires (a shot cannot be
    administered without an act — so the CIF must carry the visit).

    Shape: outpatient / completed / primary_care / vaccination purpose.
    Deterministic id derived from patient + occurrence_date + CVX so a
    re-run reuses the same id (idempotent verify).
    """
    occ = _get(imm, "occurrence_date", None)
    cvx = str(_get(imm, "vaccine_cvx", "") or "")
    if not isinstance(occ, date):
        occ = date(2000, 1, 1)
    _key = f"{patient_id}|{occ.isoformat()}|{cvx}|synth-vax".encode()
    _suffix = hashlib.sha256(_key).hexdigest()[:12]
    enc_id = f"ENC-VAX-{patient_id}-{_suffix}"
    adm = datetime(occ.year, occ.month, occ.day, 10, 0)
    is_ja = country == "JP"
    chief_en = "Vaccination visit"
    chief_ja = "予防接種"
    # Issue #1215: stamp Z23 "Encounter for immunization" as the companion
    # encounter's own admission diagnosis so FHIR emit's reasonCode reflects
    # the visit purpose (vaccination) instead of inheriting the record's
    # primary IMP admission dx (e.g. T30.0 burn for a hospitalized patient
    # who happened to also receive an in-window flu shot at a follow-up
    # visit). Z23 is a visit-reason Z-code (recognized by
    # ``is_visit_reason_zcode``), so no dangling Condition reference is
    # created — the reasonCode text/coding alone carries the semantic.
    return Encounter(
        encounter_id=enc_id,
        patient_id=patient_id,
        encounter_type=EncounterType.OUTPATIENT,
        status=EncounterStatus.COMPLETED,
        department_id="primary_care",
        admission_datetime=adm,
        discharge_datetime=adm,
        chief_complaint=chief_en,
        chief_complaint_ja=chief_ja if is_ja else "",
        priority="R",  # routine
        admission_diagnosis_code="Z23",
        admission_diagnosis_system="icd-10-cm",
    )


def _sim_window_start(ctx) -> date | None:
    """Return the sim window's start date (inclusive) or None if unresolvable.

    Reads ``ctx.config.time_range`` (used by the natural-death enricher
    already — see `modules/natural_death/enricher.py`). Falls back to
    None on any parse failure so callers can decide policy (pre-sim
    historical doses stay unlinked when the window is unknown).
    """
    cfg = getattr(ctx, "config", None)
    if cfg is None:
        return None
    raw = getattr(cfg, "time_range", None)
    if raw is None:
        return None
    try:
        seq = tuple(raw)
    except TypeError:
        return None
    if len(seq) < 1:
        return None
    try:
        return date.fromisoformat(str(seq[0])[:10])
    except ValueError:
        return None


def enrich_immunizations(ctx) -> None:
    country = _get(_get(ctx, "config"), "country", "US") if _get(ctx, "config") else "US"
    schedule = load_schedule(country)
    # RM-3: pass a sorted nurse roster so administered_by can be
    # populated per-Immunization deterministically (real JP practice: nurses
    # administer routine vaccinations).
    roster = getattr(ctx, "roster", None)
    nurse_ids = []
    if roster and hasattr(roster, "members"):
        nurse_ids = sorted(m.staff_id for m in roster.members if getattr(m, "role", "") == "nurse")
    # Issue #1197 cross-record alignment (verify Pass 4 root fix): CIF
    # splits one patient's history into one record per encounter, so a
    # single record only sees ONE encounter — the aligner previously
    # couldn't reach the patient's other in-sim encounters. Build a
    # per-patient encounter union up-front so alignment finds any nearby
    # encounter across the patient's full record set.
    _all_encs_by_patient: dict[str, list] = {}
    for rec in ctx.records:
        patient = _get(rec, "patient")
        pid = _get(patient, "patient_id", "") if patient else ""
        if not pid:
            continue
        for enc in _get(rec, "encounters", []) or []:
            _all_encs_by_patient.setdefault(pid, []).append(enc)
    # Issue #1197 companion-encounter synthesis (verify Pass 5 gap): for
    # in-sim-window immunizations that could not be aligned to an
    # existing encounter (~25-39% of in-window doses, per Pass 5 verify),
    # emit a minimal `vaccination visit` outpatient encounter. Pre-sim
    # historical doses (patient interview / registry-recorded) stay
    # unlinked — a real visit was not simulated, so honesty > fabrication.
    country_upper = str(country or "US").upper()
    sim_start = _sim_window_start(ctx)
    for rec in ctx.records:
        patient = _get(rec, "patient")
        pid = _get(patient, "patient_id", "") if patient else ""
        rng = np.random.default_rng(derive_sub_seed(ctx.master_seed, ENRICHER_SEED_OFFSETS["immunization"], pid or "x"))
        recs = generate_immunizations(patient, schedule, _as_of(ctx, rec), rng, nurse_ids=nurse_ids)
        # Issue #1197 align — cross-record encounter pool.
        pool = _all_encs_by_patient.get(pid) or (_get(rec, "encounters", []) or [])
        recs = _align_to_encounters(recs, pool)
        # Companion synthesis for the residual in-window orphans.
        rec_encounters = _get(rec, "encounters", []) or []
        for imm in recs:
            if _get(imm, "encounter_id", "") or "":
                continue  # already aligned
            occ = _get(imm, "occurrence_date", None)
            if not isinstance(occ, date):
                continue
            # Pre-sim historical dose: mark primary_source=False and
            # leave encounter_id empty (honest boundary).
            if sim_start is not None and occ < sim_start:
                _set(imm, "primary_source", False)
                continue
            # In-window orphan: emit companion encounter for THIS record.
            # (Kept per-record to avoid cross-record encounter injection —
            # each record retains its self-contained encounter list.)
            synth = _synthesize_vaccination_encounter(imm, pid, country_upper)
            rec_encounters.append(synth)
            _set(imm, "encounter_id", synth.encounter_id)
        _set(rec, "encounters", rec_encounters)
        _set(rec, "immunizations", recs)
