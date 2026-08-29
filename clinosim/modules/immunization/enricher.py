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
        _set(rec, "immunizations", recs)
