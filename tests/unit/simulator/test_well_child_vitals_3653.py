"""Issue #3653: a well-child visit of a child aged 3 or over measures blood
pressure and respiratory rate, inside the paediatric range for the age."""

from __future__ import annotations

from datetime import date, datetime

import numpy as np
import pytest

from clinosim import determinism
from clinosim.locale.loader import load_demographics
from clinosim.locale.loaders.clinical import well_child_vitals
from clinosim.modules.observation.pediatric_ranges import age_in_completed_months, pediatric_vital_range
from clinosim.modules.patient.activator import activate_patient
from clinosim.modules.population.engine import PersonRecord
from clinosim.modules.staff.engine import StaffRoster
from clinosim.simulator.outpatient import _simulate_outpatient_visit

pytestmark = pytest.mark.unit

_VISIT = datetime(2026, 6, 18, 10, 0)


def _child_visit(age_years: int, disease: str = "well_child_school", seed: int = 5):
    dob = date(_VISIT.year - age_years, 1, 15)
    person = PersonRecord(person_id=f"T-3653-{age_years}", household_id="H", age=age_years, sex="F", date_of_birth=dob)
    patient = activate_patient(person, determinism.default_rng(seed), load_demographics("US"))
    return patient, _simulate_outpatient_visit(
        patient,
        "pediatric_visit",
        _VISIT,
        StaffRoster(),
        np.random.default_rng(seed),
        chronic_code=disease,
        followup_spec={"labs": [], "visit_reason": {"en": "Well-child visit", "ja": "健診"}},
        country="US",
    )


@pytest.mark.parametrize("age", [3, 4, 8, 12, 17])
def test_well_child_visit_of_age_3_and_over_records_bp_and_rr(age: int) -> None:
    disease = "well_child_early" if age < 5 else "well_child_school"
    patient, record = _child_visit(age, disease)
    vital = record.vital_signs[0]
    assert vital.systolic_bp is not None and vital.diastolic_bp is not None
    assert vital.respiratory_rate is not None
    assert vital.temperature_celsius is not None and vital.heart_rate is not None
    months = age_in_completed_months(patient.date_of_birth, _VISIT)
    sbp = pediatric_vital_range("systolic_bp", months)
    if sbp is not None:
        assert sbp.critical_low is None or vital.systolic_bp > sbp.critical_low
        assert sbp.critical_high is None or vital.systolic_bp < sbp.critical_high


def test_well_child_visit_of_a_2_year_old_keeps_temperature_and_heart_rate_only() -> None:
    _, record = _child_visit(2, "well_child_early")
    vital = record.vital_signs[0]
    assert vital.systolic_bp is None and vital.diastolic_bp is None and vital.respiratory_rate is None
    assert vital.temperature_celsius is not None and vital.heart_rate is not None


def test_infant_well_child_visit_unchanged() -> None:
    dob = date(2026, 1, 10)
    person = PersonRecord(person_id="T-3653-inf", household_id="H", age=0, sex="F", date_of_birth=dob)
    patient = activate_patient(person, determinism.default_rng(5), load_demographics("US"))
    record = _simulate_outpatient_visit(
        patient,
        "pediatric_visit",
        _VISIT,
        StaffRoster(),
        np.random.default_rng(5),
        chronic_code="well_child_infant",
        followup_spec={"labs": [], "visit_reason": {"en": "Well-child visit", "ja": "健診"}},
        country="US",
    )
    assert record.vital_signs[0].systolic_bp is None


def test_loader_gates_on_age_and_disease() -> None:
    assert well_child_vitals("well_child_school", 8) == frozenset({"temp", "hr", "bp", "rr"})
    assert well_child_vitals("well_child_early", 2) is None
    assert well_child_vitals("well_child_infant", 0) is None
    assert well_child_vitals("pediatric_uri", 8) is None
