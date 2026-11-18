"""Issue #3280: no lab result exists after the time of death."""

from __future__ import annotations

from datetime import datetime, timedelta

from clinosim.simulator.terminal_course import drop_results_after_death
from clinosim.types.encounter import Order, OrderResult, OrderStatus, OrderType

DEATH = datetime(2026, 1, 15, 0, 3)


def _lab(order_id: str, resulted: datetime, ordered: datetime | None = None) -> Order:
    order = Order(
        order_id=order_id,
        order_type=OrderType.LAB,
        display_name="Glucose",
        ordered_datetime=ordered or resulted - timedelta(hours=1),
    )
    order.result = OrderResult(result_datetime=resulted, lab_name="Glucose", value=218.0)
    order.status = OrderStatus.RESULTED
    return order


def test_results_after_death_are_dropped_and_earlier_kept() -> None:
    before = _lab("O1", datetime(2026, 1, 14, 22, 40))
    at = _lab("O2", DEATH)
    after = _lab("O3", datetime(2026, 1, 15, 6, 31), ordered=datetime(2026, 1, 14, 22, 0))
    orders = [before, at, after]
    results = [o.result for o in orders if o.result]

    drop_results_after_death(orders, results, DEATH)

    assert [r.result_datetime for r in results] == [before.result.result_datetime, DEATH]  # type: ignore[union-attr]
    assert after.result is None
    assert after.status == OrderStatus.CANCELLED
    assert before.status == OrderStatus.RESULTED and at.status == OrderStatus.RESULTED


def test_lab_ordered_after_death_is_removed() -> None:
    kept = _lab("O1", datetime(2026, 1, 14, 22, 40))
    late = _lab("O2", datetime(2026, 1, 15, 6, 31), ordered=datetime(2026, 1, 15, 6, 0))
    orders = [kept, late]
    results = [o.result for o in orders if o.result]

    drop_results_after_death(orders, results, DEATH)

    assert orders == [kept]
    assert results == [kept.result]
