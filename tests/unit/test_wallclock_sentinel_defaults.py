"""Verify dataclass fields that used to default to datetime.now()/date.today()
no longer read the wall clock (determinism chain, 2026-07-04).

Each assertion constructs the class with no args (or the minimal args needed)
and checks the timestamp/date field equals the fixed sentinel — proving the
default is a constant, not a live wall-clock call. See
docs/superpowers/specs/2026-07-04-determinism-chain-wallclock-removal-design.md.
"""
from __future__ import annotations

from datetime import date, datetime

import pytest

pytestmark = pytest.mark.unit

_SENTINEL_DATETIME = datetime(1970, 1, 1)
_SENTINEL_DATE = date(1970, 1, 1)


def test_physiological_state_timestamp_sentinel():
    from clinosim.types.clinical import PhysiologicalState
    assert PhysiologicalState().timestamp == _SENTINEL_DATETIME


def test_state_change_directive_timestamp_sentinel():
    from clinosim.types.clinical import StateChangeDirective
    assert StateChangeDirective().timestamp == _SENTINEL_DATETIME


def test_clinical_impression_record_date_sentinel():
    from clinosim.types.clinical import ClinicalImpressionRecord
    assert ClinicalImpressionRecord().date == _SENTINEL_DATE


def test_encounter_admission_datetime_sentinel():
    from clinosim.types.encounter import Encounter
    assert Encounter().admission_datetime == _SENTINEL_DATETIME


def test_order_result_result_datetime_sentinel():
    from clinosim.types.encounter import OrderResult
    assert OrderResult().result_datetime == _SENTINEL_DATETIME


def test_medication_administration_scheduled_datetime_sentinel():
    from clinosim.types.encounter import MedicationAdministration
    assert MedicationAdministration().scheduled_datetime == _SENTINEL_DATETIME


def test_prescription_record_issue_date_sentinel():
    from clinosim.types.encounter import PrescriptionRecord
    assert PrescriptionRecord().issue_date == _SENTINEL_DATETIME


def test_order_ordered_datetime_sentinel():
    from clinosim.types.encounter import Order
    assert Order().ordered_datetime == _SENTINEL_DATETIME


def test_vital_sign_record_timestamp_sentinel():
    from clinosim.types.encounter import VitalSignRecord
    assert VitalSignRecord().timestamp == _SENTINEL_DATETIME


def test_adl_assessment_date_sentinel():
    from clinosim.types.encounter import ADLAssessment
    assert ADLAssessment().date == _SENTINEL_DATE


def test_nursing_risk_assessment_date_sentinel():
    from clinosim.types.encounter import NursingRiskAssessment
    assert NursingRiskAssessment().date == _SENTINEL_DATE


def test_intake_output_record_date_sentinel():
    from clinosim.types.encounter import IntakeOutputRecord
    assert IntakeOutputRecord().date == _SENTINEL_DATE


def test_immunization_record_occurrence_date_sentinel():
    from clinosim.types.encounter import ImmunizationRecord
    assert ImmunizationRecord().occurrence_date == _SENTINEL_DATE


def test_procedure_record_start_end_datetime_sentinel():
    from clinosim.types.procedure import ProcedureRecord
    rec = ProcedureRecord()
    assert rec.start_datetime == _SENTINEL_DATETIME
    assert rec.end_datetime == _SENTINEL_DATETIME


def test_rehab_session_session_date_sentinel():
    from clinosim.types.procedure import RehabSession
    assert RehabSession().session_date == _SENTINEL_DATETIME


def test_differential_diagnosis_timestamp_sentinel():
    from clinosim.modules.diagnosis.engine import DifferentialDiagnosis
    assert DifferentialDiagnosis().timestamp == _SENTINEL_DATETIME


def test_update_differential_no_longer_touches_wall_clock():
    """update_differential() used to overwrite .timestamp with datetime.now()
    on every call — that assignment is now removed entirely (dead field)."""
    from clinosim.modules.diagnosis.engine import (
        initialize_differential,
        update_differential,
    )
    diff = initialize_differential()
    before = diff.timestamp
    diff = update_differential(diff, [("chest_xray_consolidation", True)])
    assert diff.timestamp == before == _SENTINEL_DATETIME


def test_hospital_state_timestamp_sentinel():
    from clinosim.modules.facility.hospital_state import HospitalState
    assert HospitalState().timestamp == _SENTINEL_DATETIME
