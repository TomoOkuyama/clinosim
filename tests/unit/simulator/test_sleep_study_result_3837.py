"""Issue #3837: the baseline polysomnography of an OSA patient has a result.

The study's apnea-hypopnea index (AHI) is recorded as a lab-pipeline result of
the visit that records the study, in the severity band of the patient's OSA
condition (AHI 5 to <15 mild, 15 to <30 moderate, 30 and over severe).
"""

from __future__ import annotations

from datetime import date, datetime

import numpy as np
import pytest

from clinosim.locale.loader import load_chronic_followup
from clinosim.modules.staff.engine import StaffRoster
from clinosim.simulator.outpatient import _simulate_outpatient_visit
from clinosim.simulator.sleep_study import sleep_study_ahi, sleep_study_rules
from clinosim.types.patient import ChronicCondition, PatientProfile

pytestmark = pytest.mark.unit

BANDS = {"mild": (5.0, 15.0), "moderate": (15.0, 30.0), "severe": (30.0, 200.0)}


def _patient(severity: str, pid: str = "POP-OSA-3837") -> PatientProfile:
    p = PatientProfile(patient_id=pid, sex="M", age=55, date_of_birth=date(1970, 1, 1))
    p.chronic_conditions = [ChronicCondition(code="G47.30", onset_date=date(2018, 3, 1), severity=severity)]
    return p


def _visit(patient: PatientProfile, when: datetime):
    return _simulate_outpatient_visit(
        patient=patient,
        visit_type="chronic_followup",
        visit_date=when,
        roster=StaffRoster(),
        rng=np.random.default_rng(0),
        chronic_code="G47.30",
        followup_spec=load_chronic_followup().get("G47.30"),
        country="US",
    )


@pytest.mark.parametrize("severity", ["mild", "moderate", "severe"])
def test_ahi_lies_in_the_severity_band(severity: str) -> None:
    lo, hi = BANDS[severity]
    for i in range(40):
        ahi = sleep_study_ahi(f"POP-{i}", severity)
        assert lo <= ahi < hi


def test_ahi_is_deterministic_and_patient_specific() -> None:
    assert sleep_study_ahi("POP-1", "moderate") == sleep_study_ahi("POP-1", "moderate")
    assert len({sleep_study_ahi(f"POP-{i}", "moderate") for i in range(20)}) > 5


def test_rules_carry_a_source() -> None:
    assert sleep_study_rules().analyte == "AHI"


def test_first_visit_records_the_ahi_with_the_study() -> None:
    patient = _patient("moderate")
    rec = _visit(patient, datetime(2025, 8, 1, 10, 0))
    assert any(p.procedure_code == "95810" for p in rec.procedures)
    ahi = [r for r in rec.lab_results if r.lab_name == "AHI"]
    assert len(ahi) == 1
    assert 15.0 <= float(ahi[0].value) < 30.0
    assert ahi[0].unit == "{events}/h"
    assert ahi[0].flag == "H"  # AHI >= 5 is abnormal
    order = next(o for o in rec.orders if o.display_name == "AHI")
    assert order.result is ahi[0]
    study = next(p for p in rec.procedures if p.procedure_code == "95810")
    assert ahi[0].result_datetime >= study.end_datetime


def test_later_visits_record_no_second_ahi() -> None:
    patient = _patient("mild")
    _visit(patient, datetime(2025, 8, 1, 10, 0))
    rec2 = _visit(patient, datetime(2026, 2, 1, 10, 0))
    assert not [r for r in rec2.lab_results if r.lab_name == "AHI"]
