"""One forward month loop for every phase (Issue #2169)."""

from __future__ import annotations

from datetime import date, datetime

import pytest

from clinosim.simulator.phases._forward_loop import EventQueue, monthly_ed_slot_count

pytestmark = pytest.mark.unit


def test_queue_pops_in_date_then_kind_order() -> None:
    q = EventQueue()
    q.push(datetime(2025, 3, 9, 10), "ed", "c")
    q.push(datetime(2025, 3, 2, 18), "calendar", "b")
    q.push(datetime(2025, 3, 2, 8), "calendar", "a")
    q.push(datetime(2025, 3, 2, 23), "life", "first")  # admissions lead their day
    q.push(datetime(2025, 4, 1), "calendar", "next-month")
    popped = [item.payload for item in q.pop_through(date(2025, 3, 31))]
    assert popped == ["first", "a", "b", "c"]
    assert [item.payload for item in q.pop_through(date(2025, 4, 30))] == ["next-month"]


def test_queue_accepts_events_pushed_while_draining() -> None:
    q = EventQueue()
    q.push(datetime(2025, 3, 2), "life", "admission")
    out = []
    for item in q.pop_through(date(2025, 3, 31)):
        out.append(item.payload)
        if item.payload == "admission":
            q.push(datetime(2025, 3, 20), "readmission", "readmit")
    assert out == ["admission", "readmit"]


def test_monthly_ed_slot_count_carries_fractions() -> None:
    carry = 0.0
    total = 0
    for _ in range(12):
        n, carry = monthly_ed_slot_count(n_persons=100, rate_per_1000_person_years=380, carry=carry)
        total += n
    assert total == 38  # 100 persons x 380 / 1000 over a year, no rounding loss
