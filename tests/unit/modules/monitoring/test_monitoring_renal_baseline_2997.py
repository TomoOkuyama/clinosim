"""Issue #2997: monitoring labs added to a visit (a screening mammogram, a
clinic visit) follow the patient's own physiological state, so a CKD
patient's creatinine stays on their renal baseline instead of returning to
normal for one visit."""

from __future__ import annotations

from datetime import datetime

import pytest

from clinosim.modules.monitoring.enricher import _derive_true_labs_for_patient
from clinosim.modules.physiology.engine import initialize_state, medication_flags_from_context
from clinosim.simulator.lab_pipeline import patient_true_labs
from clinosim.types.patient import ChronicCondition, PatientPhysiologicalProfile, PatientProfile

pytestmark = pytest.mark.unit

_AT = datetime(2026, 1, 23, 9, 30)


def _ckd_patient() -> PatientProfile:
    return PatientProfile(
        patient_id="POP-2997",
        sex="F",
        age=68,
        physiological_profile=PatientPhysiologicalProfile(renal_reserve=0.55),
        chronic_conditions=[ChronicCondition(code="N18", severity_score=0.8, stage="CKD G4")],
    )


def test_a_screening_visit_creatinine_uses_the_patients_ckd_state() -> None:
    patient = _ckd_patient()
    labs = _derive_true_labs_for_patient(patient, _AT)
    state = initialize_state(patient.physiological_profile, patient.chronic_conditions, patient.patient_id)
    clinic = patient_true_labs(state, patient, _AT, medication_flags_from_context(patient))
    assert labs["Creatinine"] == pytest.approx(clinic["Creatinine"])
    assert labs["Creatinine"] >= 2.0
    assert labs["K"] == pytest.approx(clinic["K"])


def test_a_patient_with_healthy_kidneys_keeps_a_normal_creatinine() -> None:
    patient = PatientProfile(patient_id="POP-2997-N", sex="M", age=50)
    assert _derive_true_labs_for_patient(patient, _AT)["Creatinine"] < 1.3
