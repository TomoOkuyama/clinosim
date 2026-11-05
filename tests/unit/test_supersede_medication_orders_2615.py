"""Issue #2615: one active order per drug, and a carbapenem switch stops the earlier beta-lactam."""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from clinosim.modules.order.supersede import enrich_supersede_orders
from clinosim.types.encounter import MedicationAdministration, Order, OrderStatus, OrderType

pytestmark = pytest.mark.unit

_T0 = datetime(2025, 12, 14, 23, 45)


def _order(oid: str, name: str, at: datetime) -> Order:
    return Order(
        order_id=oid,
        encounter_id="ENC-1",
        patient_id="P1",
        order_type=OrderType.MEDICATION,
        display_name=name,
        ordered_datetime=at,
        status=OrderStatus.PLACED,
    )


def _mars(oid: str, name: str, start: datetime, n: int, every_h: int) -> list[MedicationAdministration]:
    return [
        MedicationAdministration(
            order_id=oid,
            drug_name=name,
            scheduled_datetime=start + timedelta(hours=every_h * i),
            actual_datetime=start + timedelta(hours=every_h * i),
        )
        for i in range(n)
    ]


def _run(orders, mars):
    rec = SimpleNamespace(orders=orders, medication_administrations=mars, encounters=[])
    enrich_supersede_orders(SimpleNamespace(records=[rec]))
    return rec


def test_a_second_order_for_the_same_drug_stops_the_first() -> None:
    first = _order("O1", "Meropenem 2 g IV q8h", _T0)
    second = _order("O2", "Meropenem 2 g IV q8h", _T0 + timedelta(hours=24))
    mars = _mars("O1", "Meropenem", _T0, 9, 8) + _mars("O2", "Meropenem", second.ordered_datetime, 6, 8)
    rec = _run([first, second], mars)
    assert first.status == OrderStatus.STOPPED and second.status == OrderStatus.PLACED
    assert second.prior_order_id == "O1"
    assert all(
        m.actual_datetime < second.ordered_datetime for m in rec.medication_administrations if m.order_id == "O1"
    )


def test_a_carbapenem_switch_stops_the_earlier_beta_lactam() -> None:
    pip = _order("O1", "Piperacillin/Tazobactam 4.5 g IV q6h", _T0)
    mero = _order("O2", "Meropenem 1 g IV q8h", _T0 + timedelta(hours=48))
    rec = _run([pip, mero], _mars("O1", "Piperacillin/Tazobactam", _T0, 16, 6))
    assert pip.status == OrderStatus.STOPPED
    assert all(m.actual_datetime < mero.ordered_datetime for m in rec.medication_administrations)


def test_a_planned_combination_is_left_alone() -> None:
    amp = _order("O1", "Ampicillin 2 g IV q4h", _T0)
    ctx = _order("O2", "Ceftriaxone 2 g IV q12h", _T0 + timedelta(minutes=10))
    _run([amp, ctx], [])
    assert amp.status == OrderStatus.PLACED and ctx.status == OrderStatus.PLACED


def test_the_switch_is_when_the_new_drug_is_first_given() -> None:
    first = _order("O1", "Micafungin 100 mg IV daily", _T0)
    second = _order("O2", "Micafungin 150 mg IV daily", _T0 + timedelta(hours=26))
    given_early = _mars("O2", "Micafungin", _T0 + timedelta(hours=24, minutes=10), 1, 24)
    old = _mars("O1", "Micafungin", _T0 + timedelta(hours=24, minutes=20), 1, 24)
    rec = _run([first, second], old + given_early)
    assert [m.order_id for m in rec.medication_administrations] == ["O2"]


def test_a_prn_order_does_not_replace_the_scheduled_one() -> None:
    sched = _order("O1", "Acetaminophen 1000 mg IV q6h", _T0)
    prn = _order("O2", "Acetaminophen 1000 mg IV q6h PRN", _T0 + timedelta(hours=2))
    prn.frequency = "q6h PRN"
    _run([sched, prn], [])
    assert sched.status == OrderStatus.PLACED and prn.status == OrderStatus.PLACED
