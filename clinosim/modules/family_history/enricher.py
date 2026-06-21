"""Family history enricher (AD-55 Base, AD-56 post_records).

Seeded by person_id so the family history is identical across a patient's
encounters and the main simulation stream is untouched (AD-16).
"""
from __future__ import annotations

import numpy as np

from clinosim.modules.family_history.engine import generate_family_history
from clinosim.simulator.seeding import derive_sub_seed

_FH_SEED_OFFSET = 0x4648  # "FH"


def _get(obj, name, default=None):
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def enrich_family_history(ctx) -> None:
    country = _get(_get(ctx, "config"), "country", "US") if _get(ctx, "config") else "US"
    for rec in ctx.records:
        patient = _get(rec, "patient")
        pid = _get(patient, "patient_id", "") if patient else ""
        age = int(_get(patient, "age", 0) or 0) if patient else 0
        conditions = _get(patient, "chronic_conditions", []) if patient else []
        rng = np.random.default_rng(derive_sub_seed(ctx.master_seed, _FH_SEED_OFFSET, pid or "x"))
        fams = generate_family_history(age, conditions, country, rng)
        if isinstance(rec, dict):
            rec["family_history"] = fams
        else:
            rec.family_history = fams
