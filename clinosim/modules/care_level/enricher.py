"""JP 要介護度 enricher (AD-55 Base, AD-56 post_records, JP only).

Seeded by person_id so the value is stable across encounters and the main
simulation stream is untouched (AD-16).

Issue #940: 介護保険 (LTCI) eligibility gate. 要介護度 does not apply below
age 40, and only 相当疾病 patients qualify in the 40-64 band (第2号被保険者).
The gate runs after ``assign_care_level`` so the per-patient sub-RNG advances
identically whether or not the patient is eligible — code drops to empty
for the ineligible cohort without cascading to any other patient's RNG.
"""

from __future__ import annotations

import numpy as np

from clinosim.modules._shared import get_attr_or_key as _get
from clinosim.modules._shared import set_attr_or_key as _set
from clinosim.modules.care_level.engine import (
    assign_care_level,
    load_reference,
    patient_qualifies_for_secondary_ltci,
)
from clinosim.seeding import ENRICHER_SEED_OFFSETS, derive_sub_seed


def _chronic_code(entry) -> str:
    """Return the ICD-10 code string from a chronic-conditions list entry.

    The list is heterogeneous by design: population/engine writes bare ICD
    strings; patient/activator writes ``ChronicCondition`` dataclasses;
    CIF-loaded records round-trip those dataclasses as dicts. Handle all
    three shapes so this filter works on both live and reloaded records.
    """
    if isinstance(entry, str):
        return entry
    if isinstance(entry, dict):
        return str(entry.get("code", "") or "")
    return str(getattr(entry, "code", "") or "")


def _ltci_eligible(age: int, patient) -> bool:
    """Apply Issue #940 eligibility gates before emitting a care-level code."""
    gates = load_reference().get("eligibility_gates") or {}
    primary = int(gates.get("primary_insured_min_age", 65))
    secondary = int(gates.get("secondary_insured_min_age", 40))
    if age >= primary:
        return True
    if age < secondary:
        return False
    codes = [_chronic_code(c) for c in (_get(patient, "chronic_conditions", []) or [])]
    return patient_qualifies_for_secondary_ltci(codes)


def enrich_care_level(ctx) -> None:
    country = _get(_get(ctx, "config"), "country", "US") if _get(ctx, "config") else "US"
    for rec in ctx.records:
        patient = _get(rec, "patient")
        pid = _get(patient, "patient_id", "") if patient else ""
        age = int(_get(patient, "age", 0) or 0) if patient else 0
        rng = np.random.default_rng(derive_sub_seed(ctx.master_seed, ENRICHER_SEED_OFFSETS["care_level"], pid or "x"))
        code = assign_care_level(age, country, rng)
        # Issue #940: enforce 介護保険 eligibility AFTER the (RNG-consuming)
        # draw so per-patient RNG shape is untouched — the ineligible
        # cohort loses only the emitted value.
        if code and not _ltci_eligible(age, patient):
            code = ""
        _set(rec, "care_level", code)
