"""ED troponin is drawn twice when the protocol asks for it or when it is raised (Issue #2854)."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from clinosim.simulator.emergency import _serial_repeat
from clinosim.types.encounter import Encounter, Order, OrderResult, OrderStatus, OrderType
from clinosim.types.patient import PatientProfile

pytestmark = pytest.mark.unit

_T0 = datetime(2024, 6, 14, 9, 30)


def _first(flag: str | None) -> Order:
    return Order(
        order_id="ORD-ENC-1-ED-L0",
        patient_id="PT-1",
        order_type=OrderType.LAB,
        display_name="Troponin",
        urgency="stat",
        ordered_datetime=_T0,
        status=OrderStatus.RESULTED,
        result=OrderResult(result_datetime=_T0 + timedelta(minutes=50), lab_name="Troponin_I", value=0.02, flag=flag),
    )


def _encounter() -> Encounter:
    enc = Encounter(encounter_id="ENC-1", patient_id="PT-1")
    enc.discharge_datetime = _T0 + timedelta(hours=2)
    return enc


def _repeat(spec: dict, flag: str | None, enc: Encounter) -> Order | None:
    patient = PatientProfile(patient_id="PT-1", age=60, sex="M")
    return _serial_repeat(_first(flag), spec, "Troponin_I", 0.02, patient, "US", enc, "LT-1", flag=flag)


def test_serial_spec_draws_a_second_troponin_three_hours_later_and_keeps_the_visit_open() -> None:
    enc = _encounter()
    repeat = _repeat({"test": "Troponin", "serial": True, "interval_hours": 3}, None, enc)
    assert repeat is not None and repeat.result is not None
    assert repeat.order_id == "ORD-ENC-1-ED-L0-R"
    assert repeat.ordered_datetime == _T0 + timedelta(hours=3)
    assert repeat.result.result_datetime > repeat.ordered_datetime
    assert enc.discharge_datetime is not None and enc.discharge_datetime > repeat.result.result_datetime


def test_raised_troponin_is_repeated_even_without_serial() -> None:
    assert _repeat({"test": "Troponin"}, "H", _encounter()) is not None


def test_normal_single_troponin_is_not_repeated() -> None:
    assert _repeat({"test": "Troponin"}, None, _encounter()) is None
