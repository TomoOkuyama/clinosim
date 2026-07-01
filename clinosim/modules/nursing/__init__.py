"""Nursing module (Tier 1 #3 α-min-2 always-on Module, AD-64).

Inpatient/ICU/rehab encounters: primary_nurse assignment +
nursing assessment scaffolding (ADL / risk assessment / disease-specific focus).

POST_ENCOUNTER enricher, order=94 (after triage=93, before document=95).
"""

from __future__ import annotations

from clinosim.modules.nursing.engine import (
    INPATIENT_ENCOUNTER_TYPES,
    SUPPORTED_ADL_CATEGORIES,
    SUPPORTED_RISK_ASSESSMENTS,
    assign_primary_nurse,
    load_nursing_assessment,
)

__all__ = [
    "INPATIENT_ENCOUNTER_TYPES",
    "SUPPORTED_ADL_CATEGORIES",
    "SUPPORTED_RISK_ASSESSMENTS",
    "assign_primary_nurse",
    "load_nursing_assessment",
]
