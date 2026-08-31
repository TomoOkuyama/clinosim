"""Chronic-medication-driven monitoring pipeline (Issue #757).

Injects standard-of-care monitoring labs into chronic follow-up visits based
on the patient's ``current_medications`` list. Complements the disease-YAML
``labs`` path — a warfarin-treated DVT patient whose only chronic
follow-up is for hypertension still needs INR checks that the HTN visit
schedule doesn't specify.

Data-driven from ``reference_data/med_lab_mapping.yaml`` (medication name
patterns → monitoring labs + per-visit probability). Consumers call
:func:`monitoring_labs_for_patient` from the visit-schedule dispatch.
"""

from __future__ import annotations

from clinosim.modules.monitoring.engine import (
    load_medication_lab_mapping,
    monitoring_labs_for_patient,
)

__all__ = [
    "load_medication_lab_mapping",
    "monitoring_labs_for_patient",
]
