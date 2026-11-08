"""The health checkup lowers LDL with the shared statin response (Issue #2928).

For the same patient and statin, the fraction of the untreated LDL removed at
the checkup equals the fraction removed on the encounter lab path
(``medication_flags_from_context`` -> ``_add_lipid_labs``).
"""

from __future__ import annotations

import numpy as np
import pytest

from clinosim.modules.health_checkup import engine as checkup
from clinosim.modules.physiology.engine import derive_lab_values, medication_flags_from_context
from clinosim.types.clinical import PhysiologicalState
from clinosim.types.patient import ChronicCondition, HomeMedication, PatientProfile

pytestmark = pytest.mark.unit


def _patient(patient_id: str, *meds: HomeMedication) -> PatientProfile:
    patient = PatientProfile(patient_id=patient_id, age=62, sex="M")
    patient.chronic_conditions = [ChronicCondition(code="E78.5", system="icd-10-cm")]
    patient.current_medications = [
        HomeMedication(drug_name="Amlodipine", dose="5mg", route="PO", frequency="daily"),
        *meds,
    ]
    return patient


def _checkup_ldl(patient: PatientProfile) -> float:
    return checkup._derive_checkup_values(patient, np.random.default_rng(0))["LDL"]


def _encounter_ldl(patient: PatientProfile) -> float:
    flags = medication_flags_from_context(patient)
    labs = derive_lab_values(PhysiologicalState(), sex="M", age=62, has_dyslipidemia=True, **flags)  # type: ignore[arg-type]
    return labs["LDL"]


@pytest.mark.parametrize(
    ("patient_id", "drug", "dose"),
    [
        ("pt-2928-a", "Atorvastatin", "5mg"),  # low
        ("pt-2928-b", "Atorvastatin", "10mg"),  # moderate
        ("pt-2928-c", "Rosuvastatin", "20mg"),  # high
        ("pt-2928-d", "Simvastatin", "40mg"),  # moderate
        ("pt-2928-e", "Atorvastatin", ""),  # unreadable dose -> default intensity
    ],
)
def test_checkup_reduction_equals_encounter_reduction(
    monkeypatch: pytest.MonkeyPatch, patient_id: str, drug: str, dose: str
) -> None:
    # Without measurement noise the checkup LDL is the (treated) true value.
    monkeypatch.setattr(checkup, "LDL_MEASUREMENT_NOISE_SD", 0.0)
    statin = HomeMedication(drug_name=drug, dose=dose, route="PO", frequency="daily")
    untreated, treated = _patient(patient_id), _patient(patient_id, statin)

    checkup_fraction = 1.0 - _checkup_ldl(treated) / _checkup_ldl(untreated)
    encounter_fraction = 1.0 - _encounter_ldl(treated) / _encounter_ldl(untreated)

    assert checkup_fraction > 0.0
    assert checkup_fraction == pytest.approx(encounter_fraction, abs=1e-9)


def test_checkup_without_statin_is_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(checkup, "LDL_MEASUREMENT_NOISE_SD", 0.0)
    patient = _patient("pt-2928-none")
    assert _checkup_ldl(patient) == pytest.approx(
        checkup.LDL_BASE_MALE + 22 * checkup.LDL_AGE_SCALE_MALE + checkup.LDL_DYSLIPIDEMIA_LIFT
    )
