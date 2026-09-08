"""Immunization enricher (AD-55 Base, AD-56 post_records).

Generates each patient's vaccine history with a dedicated sub-seed so the main
simulation random stream is untouched (AD-16). occurrence dates <= snapshot (AD-32).
"""

from __future__ import annotations

from datetime import date, datetime

import numpy as np

from clinosim.modules._shared import get_attr_or_key as _get
from clinosim.modules._shared import set_attr_or_key as _set
from clinosim.modules.immunization.engine import generate_immunizations, load_schedule
from clinosim.seeding import ENRICHER_SEED_OFFSETS, derive_sub_seed


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
        # Nearest outpatient encounter within ±14 days.
        best_delta: int | None = None
        best_day: date | None = None
        best_eid: str = ""
        for _day, _eid in _enc_days:
            _delta = abs((_day - occ).days)
            if _delta > 14:
                continue
            if best_delta is None or _delta < best_delta:
                best_delta = _delta
                best_day = _day
                best_eid = _eid
        if best_day is not None and best_eid:
            _set(imm, "occurrence_date", best_day)
            _set(imm, "encounter_id", best_eid)
    return imm_recs


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
    for rec in ctx.records:
        patient = _get(rec, "patient")
        pid = _get(patient, "patient_id", "") if patient else ""
        rng = np.random.default_rng(derive_sub_seed(ctx.master_seed, ENRICHER_SEED_OFFSETS["immunization"], pid or "x"))
        recs = generate_immunizations(patient, schedule, _as_of(ctx, rec), rng, nurse_ids=nurse_ids)
        # Issue #1197 CIF-layer align: snap each immunization to the
        # nearest same-fortnight outpatient encounter and stamp
        # encounter_id. See `_align_to_encounters` for the policy.
        encounters = _get(rec, "encounters", []) or []
        recs = _align_to_encounters(recs, encounters)
        _set(rec, "immunizations", recs)
