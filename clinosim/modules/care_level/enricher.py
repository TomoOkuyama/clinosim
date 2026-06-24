"""JP 要介護度 enricher (AD-55 Base, AD-56 post_records, JP only).

Seeded by person_id so the value is stable across encounters and the main
simulation stream is untouched (AD-16)."""
from __future__ import annotations

import numpy as np

from clinosim.modules._shared import get_attr_or_key as _get
from clinosim.modules.care_level.engine import assign_care_level
from clinosim.simulator.seeding import derive_sub_seed

_CL_SEED_OFFSET = 0x434C  # "CL"


def enrich_care_level(ctx) -> None:
    country = _get(_get(ctx, "config"), "country", "US") if _get(ctx, "config") else "US"
    for rec in ctx.records:
        patient = _get(rec, "patient")
        pid = _get(patient, "patient_id", "") if patient else ""
        age = int(_get(patient, "age", 0) or 0) if patient else 0
        rng = np.random.default_rng(derive_sub_seed(ctx.master_seed, _CL_SEED_OFFSET, pid or "x"))
        code = assign_care_level(age, country, rng)
        if isinstance(rec, dict):
            rec["care_level"] = code
        else:
            rec.care_level = code
