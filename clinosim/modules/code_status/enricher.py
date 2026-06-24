"""Code status enricher (AD-55 Base, AD-56 post_records).

Seeded by encounter_id so the value is stable within an encounter and the main
simulation stream is untouched (AD-16). Assigned only to serious encounters.
"""
from __future__ import annotations

import numpy as np

from clinosim.modules._shared import get_attr_or_key as _get
from clinosim.modules.code_status.engine import assign_code_status
from clinosim.simulator.seeding import ENRICHER_SEED_OFFSETS, derive_sub_seed


def _qualifies(encounter_type: str, deceased: bool, icu: bool) -> bool:
    if encounter_type == "inpatient":
        return True
    if encounter_type == "emergency":
        return bool(deceased or icu)
    return False


def enrich_code_status(ctx) -> None:
    country = _get(_get(ctx, "config"), "country", "US") if _get(ctx, "config") else "US"
    for rec in ctx.records:
        encs = _get(rec, "encounters", []) or []
        enc = encs[0] if encs else None
        etype = _get(enc, "encounter_type", "") if enc else ""
        eid = _get(enc, "encounter_id", "") if enc else ""
        deceased = bool(_get(rec, "deceased", False))
        icu = bool(_get(rec, "icu_transferred", False))
        code = ""
        if eid and _qualifies(etype, deceased, icu):
            patient = _get(rec, "patient")
            age = int(_get(patient, "age", 0) or 0) if patient else 0
            context = "terminal" if deceased else ("icu" if icu else "routine")
            rng = np.random.default_rng(derive_sub_seed(ctx.master_seed, ENRICHER_SEED_OFFSETS["code_status"], eid))
            code = assign_code_status(age, context, country, rng)
        if isinstance(rec, dict):
            rec["code_status"] = code
        else:
            rec.code_status = code
