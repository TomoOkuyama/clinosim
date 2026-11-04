"""Outpatient visit dedup state lives in the declared ``visit_ledger`` (Issue #2574)."""

from __future__ import annotations

from datetime import date, datetime

import pytest

from clinosim.simulator.outpatient import _specialty_fanout_tick
from clinosim.types.patient import ChronicCondition, OutpatientVisitLedger, PatientProfile

pytestmark = pytest.mark.unit


def test_specialty_dedup_is_recorded_on_the_ledger_not_as_an_ad_hoc_attribute() -> None:
    patient = PatientProfile(patient_id="pt-ledger", age=55, sex="F", date_of_birth=date(1969, 1, 1))
    patient.chronic_conditions = [ChronicCondition(code="C50.9", system="icd-10-cm")]
    assert patient.visit_ledger == OutpatientVisitLedger()

    _specialty_fanout_tick(patient, datetime(2024, 3, 15))

    assert ("oncology", 2024, None) in patient.visit_ledger.specialty_visits
    assert not [name for name in vars(patient) if name.startswith("_phase")]


def test_ledger_does_not_affect_patient_equality() -> None:
    a, b = PatientProfile(patient_id="p"), PatientProfile(patient_id="p")
    a.visit_ledger.baseline_procedures.add("123")
    assert a == b
