"""Guards of docs/design-guides/medication-lifecycle-spec.md §4 (Issue #2729):
administrations of orders placed outside the daily loop draw no RNG and come
from ``placed_order_mar``."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

import pytest

from clinosim.modules.order.placed_order_mar import administrations_for, daily_times

pytestmark = pytest.mark.unit

_PKG = Path(__file__).resolve().parents[4] / "clinosim"


def test_placed_order_administrations_draw_no_rng() -> None:
    text = (_PKG / "modules/order/placed_order_mar.py").read_text(encoding="utf-8")
    assert not re.search(r"\brng\b|default_rng|random|derive_sub_seed", text)


@pytest.mark.parametrize("rel", ["modules/prophylaxis/enricher.py", "simulator/perinatal.py"])
def test_placed_order_pathways_use_the_shared_helpers(rel: str) -> None:
    assert "administrations_for(" in (_PKG / rel).read_text(encoding="utf-8")


def test_daily_times_and_administrations_are_fixed() -> None:
    times = daily_times(datetime(2025, 1, 1, 22, 0), datetime(2025, 1, 4, 10, 0), 21)
    assert times == [datetime(2025, 1, 2, 21), datetime(2025, 1, 3, 21)]
    from clinosim.types.encounter import Order

    order = Order(order_id="O1", display_name="Enoxaparin", dose_quantity=40.0, dose_unit="mg", route="SC")
    mars = administrations_for(order, times, "N1")
    assert [m.scheduled_datetime for m in mars] == times and {m.administered_by for m in mars} == {"N1"}
