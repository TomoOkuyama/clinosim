"""Issue #3918: an outpatient routine lab order is placed inside its visit.

The order used to be placed a fixed 10 minutes after the visit start, so a visit
of 9 minutes or less ended before its own lab order (JP 1374 of 8594 orders).
"""

from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np
import pytest

from clinosim.locale.loader import load_ambulatory_visit_length, load_chronic_followup
from clinosim.modules.staff.engine import StaffRoster
from clinosim.simulator import _outpatient_thresholds as thresholds
from clinosim.simulator import outpatient
from clinosim.simulator.outpatient import _simulate_outpatient_visit
from clinosim.types.patient import ChronicCondition, HomeMedication, PatientProfile

pytestmark = pytest.mark.unit

_START = datetime(2026, 1, 30, 10, 39)


def _patient() -> PatientProfile:
    patient = PatientProfile(patient_id="pt-3918", age=63, sex="M")
    patient.chronic_conditions = [ChronicCondition(code="E78", system="icd-10-cm")]
    patient.current_medications = [HomeMedication(drug_name="Atorvastatin", dose="20mg", route="PO", frequency="daily")]
    return patient


def _visit(patient: PatientProfile, country: str):
    return _simulate_outpatient_visit(
        patient,
        "chronic_followup",
        _START,
        StaffRoster(),
        np.random.default_rng(0),
        chronic_code="E78",
        followup_spec=load_chronic_followup()["E78"],
        country=country,
    )


def test_a_short_visit_gets_its_lab_order_inside_the_visit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(outpatient, "_sample_ambulatory_visit_length_minutes", lambda *a, **k: 6)
    rec = _visit(_patient(), "JP")
    enc = rec.encounters[0]
    assert enc.discharge_datetime == _START + timedelta(minutes=6)
    labs = [o for o in rec.orders if o.order_id.startswith(f"ORD-{enc.encounter_id}-OPD-L")]
    assert labs
    for o in labs:
        assert _START <= o.ordered_datetime <= enc.discharge_datetime


def test_a_long_visit_keeps_the_ten_minute_offset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(outpatient, "_sample_ambulatory_visit_length_minutes", lambda *a, **k: 40)
    rec = _visit(_patient(), "US")
    labs = [o for o in rec.orders if "-OPD-L" in o.order_id]
    assert labs
    assert {o.ordered_datetime for o in labs} == {
        _START + timedelta(minutes=thresholds.OUTPATIENT_LAB_ORDER_OFFSET_MIN)
    }


@pytest.mark.parametrize("country", ["US", "JP"])
def test_every_visit_length_the_country_can_sample_keeps_the_order_inside(
    country: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    shortest = min(b["min"] for b in load_ambulatory_visit_length(country)["visit_types"].values())
    for minutes in range(shortest, 40):
        monkeypatch.setattr(outpatient, "_sample_ambulatory_visit_length_minutes", lambda *a, m=minutes, **k: m)
        rec = _visit(_patient(), country)
        end = rec.encounters[0].discharge_datetime
        assert all(o.ordered_datetime <= end for o in rec.orders), minutes
