"""The health checkup reads the patient's lipid state for LDL (Issue #2941).

For the same patient (sex, diabetes, dyslipidemia, statin), the checkup's true
LDL (before its measurement noise) equals the LDL of the encounter lab path
(``simulator.lab_pipeline.patient_true_labs``), whatever the patient's age.
"""

from __future__ import annotations

from datetime import datetime

import numpy as np
import pytest

from clinosim.modules.health_checkup import engine as checkup
from clinosim.modules.physiology.engine import medication_flags_from_context, patient_lipid_panel
from clinosim.simulator.lab_pipeline import patient_true_labs
from clinosim.types.clinical import PhysiologicalState
from clinosim.types.patient import ChronicCondition, HomeMedication, PatientProfile

pytestmark = pytest.mark.unit


def _patient(age: int, sex: str, codes: tuple[str, ...], statin: str | None) -> PatientProfile:
    patient = PatientProfile(patient_id=f"pt-2941-{age}-{sex}-{'-'.join(codes)}-{statin}", age=age, sex=sex)
    patient.chronic_conditions = [ChronicCondition(code=c, system="icd-10-cm") for c in codes]
    if statin:
        drug, dose = statin.split()
        patient.current_medications = [HomeMedication(drug_name=drug, dose=dose, route="PO", frequency="daily")]
    return patient


def _encounter_labs(patient: PatientProfile) -> dict[str, float]:
    flags = medication_flags_from_context(patient)
    return patient_true_labs(PhysiologicalState(), patient, datetime(2025, 6, 1, 9), flags)


@pytest.mark.parametrize("age", [45, 70])
@pytest.mark.parametrize("sex", ["M", "F"])
@pytest.mark.parametrize("codes", [(), ("E78.5",), ("E11.9",), ("E78.0", "E11.9")])
@pytest.mark.parametrize("statin", [None, "Atorvastatin 10mg", "Rosuvastatin 20mg"])
def test_checkup_ldl_equals_encounter_ldl(
    monkeypatch: pytest.MonkeyPatch, age: int, sex: str, codes: tuple[str, ...], statin: str | None
) -> None:
    monkeypatch.setattr(checkup, "LDL_MEASUREMENT_NOISE_SD", 0.0)
    patient = _patient(age, sex, codes, statin)
    encounter = _encounter_labs(patient)
    checkup_ldl = checkup._derive_checkup_values(patient, np.random.default_rng(0), charted_bmi=22.5)["LDL"]
    expected = float(np.clip(encounter["LDL"], checkup.LDL_PHYSIOLOGIC_MIN, checkup.LDL_PHYSIOLOGIC_MAX))
    assert checkup_ldl == pytest.approx(expected, abs=1e-9)
    # The shared helper returns the whole encounter lipid panel.
    panel = patient_lipid_panel(patient)
    for analyte in ("TC", "HDL", "TG", "LDL"):
        assert panel[analyte] == pytest.approx(encounter[analyte], abs=1e-9)


def test_checkup_ldl_keeps_its_measurement_noise() -> None:
    patient = _patient(55, "M", ("E78.5",), None)
    true_ldl = patient_lipid_panel(patient)["LDL"]
    values = [
        checkup._derive_checkup_values(patient, np.random.default_rng(s), charted_bmi=22.5)["LDL"] for s in range(200)
    ]
    assert np.std(values) > 5.0
    assert abs(np.median(values) - true_ldl) < 3.0
