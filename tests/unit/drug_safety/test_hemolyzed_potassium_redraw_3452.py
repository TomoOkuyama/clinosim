"""Issue #3452: a hemolyzed potassium is repeated, never treated."""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from clinosim.modules.drug_safety.hyperkalemia import potassium_history, potassium_hold_from_results
from clinosim.modules.observation.hemolysis_redraw import HEMOLYZED_FLAGS, hemolysis_redraw_rules
from clinosim.simulator import daily_loop
from clinosim.types.encounter import Order, OrderResult, OrderStatus, OrderType

pytestmark = pytest.mark.unit

_AT = datetime(2026, 3, 1, 8, 0)


def _k(value: float, flag: str, at: datetime = _AT) -> OrderResult:
    return OrderResult(result_datetime=at, lab_name="K", value=value, unit="mmol/L", flag=flag)


def test_hemolyzed_k_is_not_a_trigger_or_history() -> None:
    assert potassium_hold_from_results([_k(7.2, "H*")]) is None
    assert potassium_history([_k(7.2, "H*"), _k(4.1, "")]) == ((_AT, 4.1),)
    assert potassium_hold_from_results([_k(7.2, "H*"), _k(6.3, "critical", _AT + timedelta(hours=1))]) is not None
    assert {"H*", "L*"} == HEMOLYZED_FLAGS


def _stay(seed: str):
    from clinosim.types.patient import PatientProfile

    return SimpleNamespace(
        encounter_id=f"ENC-{seed}",
        patient=PatientProfile(patient_id="POP-3452"),
        country_key="us",
        roster=SimpleNamespace(members=[], get_by_role=lambda *a, **k: []),
        hospital_state=None,
        hospital_ops=None,
    )


def _run_redraw(true_k: float, n: int = 1):
    """One hemolyzed specimen of K, redrawn; returns (run, orders)."""
    stay = _stay("A")
    base = Order(
        order_id="ORD-ENC-A-ADM-L00",
        encounter_id=stay.encounter_id,
        patient_id="POP-3452",
        order_type=OrderType.LAB,
        display_name="K",
        ordered_datetime=_AT,
        status=OrderStatus.RESULTED,
    )
    base.result = _k(7.5, "H*")
    run = SimpleNamespace(orders=[base], lab_results=[base.result])
    daily_loop._redraw_hemolyzed(stay, run, 0, {"K": true_k}, [])
    return run, base


def test_redraw_is_scheduled_and_carries_true_value() -> None:
    run, base = _run_redraw(4.2)
    redraws = [o for o in run.orders if "-REDRAW-" in o.order_id]
    assert redraws
    first = redraws[0]
    rules = hemolysis_redraw_rules()
    assert first.ordered_datetime == _AT + timedelta(minutes=rules.delay_minutes)
    assert len(redraws) <= rules.max_redraws
    last = run.orders[-1]
    if last.status == OrderStatus.RESULTED and last.result.flag not in HEMOLYZED_FLAGS:
        assert last.result.value < 6.0
        assert last.result.result_datetime > first.ordered_datetime


def test_redraw_reading_above_threshold_still_treats() -> None:
    run, _ = _run_redraw(6.8)
    good = [r for r in run.lab_results if r.flag not in HEMOLYZED_FLAGS]
    if good:
        assert potassium_hold_from_results(good) is not None


def test_cap_bounds_the_repeats() -> None:
    for i in range(40):
        stay = _stay(f"C{i}")
        base = Order(
            order_id=f"ORD-ENC-C{i}-ADM-L00",
            encounter_id=stay.encounter_id,
            patient_id="POP-3452",
            order_type=OrderType.LAB,
            display_name="K",
            ordered_datetime=_AT,
            status=OrderStatus.RESULTED,
        )
        base.result = _k(7.5, "H*")
        run = SimpleNamespace(orders=[base], lab_results=[base.result])
        daily_loop._redraw_hemolyzed(stay, run, 0, {"K": 4.0}, [])
        assert len([o for o in run.orders if "-REDRAW-" in o.order_id]) <= hemolysis_redraw_rules().max_redraws


def test_no_hemolysis_no_redraw() -> None:
    stay = _stay("N")
    base = Order(order_id="ORD-N", encounter_id="ENC-N", order_type=OrderType.LAB, display_name="K")
    base.result = _k(4.4, "")
    run = SimpleNamespace(orders=[base], lab_results=[base.result])
    daily_loop._redraw_hemolyzed(stay, run, 0, {"K": 4.4}, [])
    assert len(run.orders) == 1 and len(run.lab_results) == 1
