"""Immunization enricher (AD-55 Base, AD-56 post_records).

Generates each patient's vaccine history with a dedicated sub-seed so the main
simulation random stream is untouched (AD-16). occurrence dates <= snapshot (AD-32).
"""

from __future__ import annotations

import hashlib
from datetime import date, datetime

import numpy as np

from clinosim.modules.immunization.engine import generate_immunizations, load_schedule

_IMM_SEED_OFFSET = 0x494D  # "IM"


def _sub_seed(master_seed: int, key: str) -> int:
    h = int.from_bytes(hashlib.sha256(key.encode()).digest()[:6], "big")
    return (int(master_seed) + _IMM_SEED_OFFSET + h) % (2**32)


def _get(obj, name, default=None):
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


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
        rng = np.random.default_rng(_sub_seed(ctx.master_seed, pid or "x"))
        recs = generate_immunizations(patient, schedule, _as_of(ctx, rec), rng)
        if isinstance(rec, dict):
            rec["immunizations"] = recs
        else:
            rec.immunizations = recs
