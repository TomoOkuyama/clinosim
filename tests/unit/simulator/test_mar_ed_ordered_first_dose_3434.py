"""Issue #3434: a drug ordered in the ED of a via-ED admission is first given
from its order, not from the admission."""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

import numpy as np
import pytest

from clinosim.simulator.medication_pipeline import _generate_mar
from clinosim.types.encounter import Order, OrderStatus, OrderType
from clinosim.types.staff import StaffRoster

pytestmark = pytest.mark.unit

_ADM = datetime(2026, 3, 26, 21, 30)
_ED_START = _ADM - timedelta(minutes=210)
_ORDERED = _ED_START + timedelta(minutes=30)


def _order(**over) -> Order:
    fields = dict(
        order_id="ORD-E1-ADM-M01",
        encounter_id="E1",
        patient_id="P1",
        order_type=OrderType.MEDICATION,
        display_name="Ceftriaxone 1g",
        ordered_datetime=_ORDERED,
        status=OrderStatus.PLACED,
        route="IV",
        frequency="DAILY",
        frequency_per_day=1,
        urgency="stat",
    )
    fields.update(over)
    return Order(**fields)


def _doses(order: Order, floor: datetime | None) -> list:
    patient = SimpleNamespace(patient_id="P1", current_medications=[], age=70, baseline_vitals=None)
    return _generate_mar(
        patient, [order], 0, _ADM, roster=StaffRoster(), rng=np.random.default_rng(0), dose_floor=floor
    )


def test_stat_first_dose_follows_the_ed_order() -> None:
    doses = _doses(_order(), _ED_START)
    first = min(m.actual_datetime or m.scheduled_datetime for m in doses)
    assert _ORDERED <= first < _ADM


def test_without_a_floor_the_first_dose_waits_for_the_admission() -> None:
    doses = _doses(_order(), None)
    assert min(m.actual_datetime or m.scheduled_datetime for m in doses) >= _ADM


def test_one_time_dose_follows_the_ed_order() -> None:
    doses = _doses(_order(single_dose=True, urgency="routine"), _ED_START)
    assert len(doses) == 1
    assert _ORDERED <= doses[0].actual_datetime < _ADM


def test_order_the_evening_before_is_a_day_zero_order() -> None:
    adm = datetime(2026, 3, 27, 1, 0)
    start = adm - timedelta(minutes=210)
    ordered = start + timedelta(minutes=30)  # 22:00 the day before
    patient = SimpleNamespace(patient_id="P1", current_medications=[], age=70, baseline_vitals=None)
    one_time = _order(single_dose=True, urgency="routine", ordered_datetime=ordered)
    doses = _generate_mar(
        patient, [one_time], 0, adm, roster=StaffRoster(), rng=np.random.default_rng(0), dose_floor=start
    )
    assert len(doses) == 1 and ordered <= doses[0].actual_datetime < adm
