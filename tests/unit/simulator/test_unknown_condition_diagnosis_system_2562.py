"""Unknown-condition stays are coded in the country's diagnosis system (Issue #2562)."""

from __future__ import annotations

from datetime import date

import numpy as np
import pytest

from clinosim.modules.healthcare_system.loader import load_healthcare_config
from clinosim.modules.staff.engine import StaffRoster
from clinosim.simulator.unknown_condition import _simulate_unknown_condition
from clinosim.types.config import SimulatorConfig
from clinosim.types.patient import PatientProfile
from clinosim.types.population import LifeEvent

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(("country", "system"), [("JP", "icd-10-mhlw"), ("US", "icd-10-cm")])
def test_admission_and_discharge_diagnoses_use_the_country_system(country: str, system: str) -> None:
    patient = PatientProfile(patient_id="pt-unk")
    patient.age, patient.sex, patient.chronic_conditions, patient.current_medications = 70, "F", [], []
    event = LifeEvent(
        person_id="pt-unk",
        event_type="unknown_condition",
        timestamp=date(2026, 5, 1),
        condition_type="unknown",
        disease_id="fever_unknown",
    )
    record = _simulate_unknown_condition(
        patient,
        event,
        np.random.default_rng(0),
        load_healthcare_config(country),
        StaffRoster(),
        config=SimulatorConfig(random_seed=0, catchment_population=10, country=country),
    )
    assert record is not None
    dx = record.clinical_diagnosis
    assert (dx.admission_diagnosis_system, dx.discharge_diagnosis_system) == (system, system)
    assert dx.admission_diagnosis_code == "R50.9"
    assert dx.diagnosis_correct is False
