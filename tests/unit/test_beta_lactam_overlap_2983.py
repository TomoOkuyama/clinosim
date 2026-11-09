"""Issue #2983: a switched beta-lactam replaces the previous one, identical
concurrent orders merge, and no two beta-lactam doses fall in the same
administration slot."""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from clinosim.modules.order.supersede import enrich_supersede_orders
from clinosim.types.encounter import MedicationAdministration, Order, OrderStatus, OrderType

pytestmark = pytest.mark.unit

_T0 = datetime(2026, 3, 6, 23, 50)


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


def _closest_pair_min(mars) -> float:
    times = sorted(m.actual_datetime for m in mars)
    return min((b - a).total_seconds() / 60 for a, b in zip(times, times[1:]))


def test_escalation_to_piperacillin_tazobactam_ends_ceftriaxone() -> None:
    ctx = _order("O1", "Ceftriaxone 1 g IV daily", _T0)
    pip = _order("O2", "Piperacillin/Tazobactam 4.5 g IV q6h", _T0 + timedelta(days=2))
    mars = _mars("O1", "Ceftriaxone", _T0, 5, 24) + _mars("O2", "Piperacillin/Tazobactam", pip.ordered_datetime, 8, 6)
    rec = _run([ctx, pip], mars)
    assert ctx.status == OrderStatus.STOPPED and pip.status == OrderStatus.PLACED
    assert all(m.actual_datetime < pip.ordered_datetime for m in rec.medication_administrations if m.order_id == "O1")


def test_a_cephalosporin_switch_ends_the_earlier_cephalosporin() -> None:
    cefaz = _order("O1", "Cefazolin 2 g IV q8h", _T0)
    ctx = _order("O2", "Ceftriaxone 2 g IV daily", _T0 + timedelta(days=1))
    _run([cefaz, ctx], _mars("O1", "Cefazolin", _T0, 6, 8))
    assert cefaz.status == OrderStatus.STOPPED


def test_identical_concurrent_orders_are_merged() -> None:
    a = _order("O1", "Piperacillin/Tazobactam 4.5 g IV q6h", _T0)
    b = _order("O2", "Piperacillin/Tazobactam 4.5 g IV q6h", _T0)
    mars = _mars("O1", "Piperacillin/Tazobactam", _T0, 8, 6) + _mars(
        "O2", "Piperacillin/Tazobactam", _T0 + timedelta(minutes=5), 8, 6
    )
    rec = _run([a, b], mars)
    assert a.status == OrderStatus.PLACED
    assert b.status == OrderStatus.CANCELLED
    assert {m.order_id for m in rec.medication_administrations} == {"O1"}
    assert len(rec.medication_administrations) == 8


def test_two_carbapenems_ordered_together_keep_one() -> None:
    mero = _order("O1", "Meropenem 1 g IV q8h", _T0)
    imi = _order("O2", "Imipenem/Cilastatin 500 mg IV q6h", _T0)
    mars = _mars("O1", "Meropenem", _T0, 6, 8) + _mars("O2", "Imipenem/Cilastatin", _T0, 6, 6)
    rec = _run([mero, imi], mars)
    assert [mero.status, imi.status] == [OrderStatus.PLACED, OrderStatus.CANCELLED]
    assert {m.order_id for m in rec.medication_administrations} == {"O1"}


def test_the_replaced_drugs_dose_in_the_switch_slot_is_not_given_twice() -> None:
    # The old order's 00:07 dose and the new drug's first dose at 00:12 are the
    # same administration slot: the new drug's dose replaces the old one. (The
    # new order is charted after its first dose, as escalation orders are.)
    pip = _order("O1", "Piperacillin/Tazobactam 4.5 g IV q6h", _T0)
    mero = _order("O2", "Meropenem 2 g IV q8h", _T0 + timedelta(days=3))
    old = _mars("O1", "Piperacillin/Tazobactam", _T0 + timedelta(minutes=17), 9, 6)  # last at +48h17m
    new = _mars("O2", "Meropenem", _T0 + timedelta(days=2, minutes=22), 4, 8)
    rec = _run([pip, mero], old + new)
    assert _closest_pair_min(rec.medication_administrations) >= 60
    assert pip.status == OrderStatus.STOPPED


def test_ampicillin_added_to_ceftriaxone_is_still_a_combination() -> None:
    ctx = _order("O1", "Ceftriaxone 2 g IV q12h", _T0)
    amp = _order("O2", "Ampicillin 2 g IV q4h", _T0 + timedelta(hours=2))
    _run([ctx, amp], [])
    assert ctx.status == OrderStatus.PLACED and amp.status == OrderStatus.PLACED


def test_a_one_time_prophylactic_dose_replaces_nothing() -> None:
    ctx = _order("O1", "Ceftriaxone 1 g IV daily", _T0)
    cefaz = _order("O2", "Cefazolin 2 g IV", _T0 + timedelta(days=1))
    cefaz.frequency = "once"
    _run([ctx, cefaz], [])
    assert ctx.status == OrderStatus.PLACED and cefaz.status == OrderStatus.PLACED


def test_an_order_stopped_by_a_discontinue_marker_is_still_cut_at_the_switch() -> None:
    pip = _order("O1", "Piperacillin/Tazobactam 4.5 g IV q6h", _T0)
    pip.status = OrderStatus.STOPPED  # flipped by a DISCONTINUE marker, its doses not ended
    mero = _order("O2", "Meropenem 2 g IV q8h", _T0 + timedelta(days=2))
    old = _mars("O1", "Piperacillin/Tazobactam", _T0, 16, 6)
    new = _mars("O2", "Meropenem", mero.ordered_datetime, 4, 8)
    rec = _run([pip, mero], old + new)
    assert all(m.actual_datetime < mero.ordered_datetime for m in rec.medication_administrations if m.order_id == "O1")


def test_a_maintenance_order_placed_with_a_loading_dose_is_kept() -> None:
    load = _order("O1", "Aspirin 325 mg PO", _T0)
    load.frequency = "once"
    daily = _order("O2", "Aspirin 81 mg PO daily", _T0)
    rec = _run(
        [load, daily], _mars("O1", "Aspirin", _T0, 1, 24) + _mars("O2", "Aspirin", _T0 + timedelta(days=1), 3, 24)
    )
    assert load.status == OrderStatus.PLACED and daily.status == OrderStatus.PLACED
    assert len(rec.medication_administrations) == 4


def test_the_duplicate_that_is_given_is_the_one_kept() -> None:
    bare = _order("O1", "Prednisolone", _T0)
    dosed = _order("O2", "Prednisolone 40 mg PO daily x5 days", _T0)
    rec = _run([bare, dosed], _mars("O2", "Prednisolone", _T0, 5, 24))
    assert [bare.status, dosed.status] == [OrderStatus.CANCELLED, OrderStatus.PLACED]
    assert len(rec.medication_administrations) == 5


def test_an_order_started_while_the_new_drug_runs_is_not_replaced_by_it() -> None:
    # The carbapenem was charted from the evening before its order time; a
    # cephalosporin started the next morning is an addition to it, not the
    # drug it replaced, so its doses stay on the MAR.
    mero = _order("O1", "Meropenem 2g IV q8h", _T0 + timedelta(hours=16))
    ctx = _order("O2", "Ceftriaxone 1 g IV daily", _T0 + timedelta(hours=8))
    mars = _mars("O1", "Meropenem", _T0, 6, 8) + _mars("O2", "Ceftriaxone", ctx.ordered_datetime, 2, 24)
    rec = _run([mero, ctx], mars)
    kept = [m for m in rec.medication_administrations if m.drug_name == "Ceftriaxone"]
    assert len(kept) == 2
    assert ctx.status == OrderStatus.PLACED
