"""Immunization enricher (AD-55 Base, AD-56 post_records).

Generates each patient's vaccine history with a dedicated sub-seed so the main
simulation random stream is untouched (AD-16). occurrence dates <= snapshot (AD-32).
"""

from __future__ import annotations

from datetime import date, datetime

import numpy as np

from clinosim.modules._shared import get_attr_or_key as _get
from clinosim.modules.immunization.engine import generate_immunizations, load_schedule
from clinosim.simulator.seeding import derive_sub_seed

_IMM_SEED_OFFSET = 0x494D  # "IM"


def _as_of(ctx, rec) -> date:
    snap = _get(_get(ctx, "config"), "snapshot_date", None) if _get(ctx, "config") else None
    if snap:
        y, m, d = (int(x) for x in str(snap).split("-"))
        return date(y, m, d)
    # else: latest encounter admission date, else today
    encs = _get(rec, "encounters", []) or []
    dates = []
    for e in encs:
        adm = _get(e, "admission_datetime")
        if isinstance(adm, datetime):
            dates.append(adm.date())
    return max(dates) if dates else date.today()


def enrich_immunizations(ctx) -> None:
    country = _get(_get(ctx, "config"), "country", "US") if _get(ctx, "config") else "US"
    schedule = load_schedule(country)
    for rec in ctx.records:
        patient = _get(rec, "patient")
        pid = _get(patient, "patient_id", "") if patient else ""
        rng = np.random.default_rng(derive_sub_seed(ctx.master_seed, _IMM_SEED_OFFSET, pid or "x"))
        recs = generate_immunizations(patient, schedule, _as_of(ctx, rec), rng)
        if isinstance(rec, dict):
            rec["immunizations"] = recs
        else:
            rec.immunizations = recs
