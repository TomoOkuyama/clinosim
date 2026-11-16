"""Issue #3311: no medication administration precedes its order.

The inpatient daily loop dates an order placed on hospital day N at
``admission + N days + 10 h``; for an evening admission that time falls on
the next calendar day, while the MAR of loop day N gave the drug on the
earlier calendar day. A continued home medication (ordered one hour after
admission) was likewise given by the day-0 first dose before it was ordered.
Every administration is now scheduled and given at or after the order time.
"""

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
_FREQ = {1: "DAILY", 2: "BID", 3: "TID", 4: "QID"}


def _order(ordered: datetime, *, freq_per_day: int, order_id: str = "ORD-E1-ESC-D1-ACETAMIN") -> Order:
    return Order(
        order_id=order_id,
        encounter_id="E1",
        patient_id="P1",
        order_type=OrderType.MEDICATION,
        display_name="Acetaminophen 500mg",
        ordered_datetime=ordered,
        status=OrderStatus.PLACED,
        route="PO",
        frequency=_FREQ[freq_per_day],
        frequency_per_day=freq_per_day,
    )


def _mar(order: Order, days: int) -> list:
    patient = SimpleNamespace(patient_id="P1", current_medications=[], age=70, baseline_vitals=None)
    out: list = []
    for day in range(days):
        out += _generate_mar(patient, [order], day, _ADM, roster=StaffRoster(), rng=np.random.default_rng(day))
    return out


@pytest.mark.parametrize("freq_per_day", [1, 2, 3, 4])
def test_order_crossing_midnight_has_no_dose_before_its_order_time(freq_per_day: int) -> None:
    ordered = _ADM + timedelta(days=1, hours=10)  # day-1 order, next calendar day 07:30
    doses = _mar(_order(ordered, freq_per_day=freq_per_day), 4)
    assert doses
    assert all(m.scheduled_datetime >= ordered for m in doses)
    assert all(m.actual_datetime is None or m.actual_datetime >= ordered for m in doses)


def test_first_dose_is_the_first_slot_after_the_order_time() -> None:
    ordered = datetime(2026, 3, 28, 10, 0)
    doses = sorted(m.scheduled_datetime for m in _mar(_order(ordered, freq_per_day=3), 4))
    assert doses[0] == datetime(2026, 3, 28, 14, 0)


def test_order_after_every_slot_of_its_day_gets_one_first_dose_after_the_order() -> None:
    ordered = datetime(2026, 3, 28, 10, 0)
    doses = sorted(m.scheduled_datetime for m in _mar(_order(ordered, freq_per_day=1), 4))
    assert ordered < doses[0] < ordered + timedelta(hours=1)
    assert doses[1:] == [datetime(2026, 3, 29, 8, 0)]


def test_home_medication_ordered_after_admission_is_not_given_before_its_order() -> None:
    ordered = _ADM + timedelta(minutes=60)
    doses = _mar(_order(ordered, freq_per_day=1, order_id="ORD-E1-HM-00"), 3)
    assert doses
    assert all(m.scheduled_datetime >= ordered for m in doses)
    assert all(m.actual_datetime is None or m.actual_datetime >= ordered for m in doses)


def test_stat_admission_order_placed_after_midnight_keeps_its_prompt_first_dose() -> None:
    adm = datetime(2026, 6, 7, 23, 53)
    order = _order(datetime(2026, 6, 8, 0, 49), freq_per_day=4, order_id="ORD-E1-ADM-M01")
    order.urgency = "stat"
    patient = SimpleNamespace(patient_id="P1", current_medications=[], age=70, baseline_vitals=None)
    doses: list = []
    for day in range(2):
        doses += _generate_mar(patient, [order], day, adm, roster=StaffRoster(), rng=np.random.default_rng(day))
    first = min(m.scheduled_datetime for m in doses)
    assert order.ordered_datetime < first <= order.ordered_datetime + timedelta(hours=1)
