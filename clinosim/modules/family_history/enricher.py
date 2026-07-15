"""Family history enricher (AD-55 Base, AD-56 post_records).

Seeded by person_id so the family history is identical across a patient's
encounters and the main simulation stream is untouched (AD-16).
"""

from __future__ import annotations

import numpy as np

from clinosim.modules._shared import get_attr_or_key as _get
from clinosim.modules._shared import set_attr_or_key as _set
from clinosim.modules.family_history.engine import generate_family_history
from clinosim.simulator.seeding import ENRICHER_SEED_OFFSETS, derive_sub_seed


def enrich_family_history(ctx) -> None:
    country = _get(_get(ctx, "config"), "country", "US") if _get(ctx, "config") else "US"
    for rec in ctx.records:
        patient = _get(rec, "patient")
        pid = _get(patient, "patient_id", "") if patient else ""
        age = int(_get(patient, "age", 0) or 0) if patient else 0
        conditions = _get(patient, "chronic_conditions", []) if patient else []
        rng = np.random.default_rng(
            derive_sub_seed(ctx.master_seed, ENRICHER_SEED_OFFSETS["family_history"], pid or "x")
        )  # noqa: E501
        fams = generate_family_history(age, conditions, country, rng)
        _set(rec, "family_history", fams)
