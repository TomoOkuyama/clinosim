"""Without hospital state, imaging orders use the imaging timing model (Issue #2202)."""

from __future__ import annotations

from datetime import datetime

import numpy as np
import pytest

from clinosim.modules.order import engine as order_engine
from clinosim.types.encounter import Order, OrderType

pytestmark = pytest.mark.unit


def _order(kind: OrderType, name: str) -> Order:
    return Order(order_type=kind, display_name=name, urgency="routine", ordered_datetime=datetime(2025, 3, 4, 10, 0))


def test_imaging_order_without_state_uses_the_imaging_model(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(
        order_engine, "calculate_imaging_result_time", lambda o, rng: calls.append("imaging") or o.ordered_datetime
    )
    monkeypatch.setattr(
        order_engine, "calculate_lab_result_time", lambda o, rng: calls.append("lab") or o.ordered_datetime
    )
    order_engine.calculate_result_time_from_state(
        _order(OrderType.IMAGING, "CT chest"), None, {}, np.random.default_rng(0)
    )
    order_engine.calculate_result_time_from_state(_order(OrderType.LAB, "CRP"), None, {}, np.random.default_rng(0))
    assert calls == ["imaging", "lab"]
