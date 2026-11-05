"""Archetype add_labs entries are routed to coded orders (Issue #2583)."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from clinosim.simulator.daily_loop import _add_archetype_workup
from clinosim.types.encounter import OrderType

pytestmark = pytest.mark.unit


def _orders(add_labs: list[str]) -> list:
    stay = SimpleNamespace(
        encounter_id="ENC-1",
        archetype="treatment_resistant",
        admission_time=datetime(2025, 3, 1, 9, 0),
        patient=SimpleNamespace(patient_id="pt-1"),
    )
    run = SimpleNamespace(orders=[])
    _add_archetype_workup(stay, run, 2, {"add_labs": add_labs})  # type: ignore[arg-type]
    return run.orders


def test_a_group_becomes_its_component_orders_with_distinct_ids() -> None:
    orders = _orders(["DIC_panel"])
    assert [o.display_name for o in orders] == ["PT", "PT_INR", "APTT", "Fibrinogen", "D_dimer", "Plt"]
    assert {o.order_type for o in orders} == {OrderType.LAB}
    assert len({o.order_id for o in orders}) == 6


def test_an_imaging_study_is_ordered_as_imaging_and_a_vital_sign_not_at_all() -> None:
    orders = _orders(["Chest_Xray", "SpO2", "K_stat"])
    assert [(o.display_name, o.order_type) for o in orders] == [
        ("Chest_Xray", OrderType.IMAGING),
        ("K_stat", OrderType.LAB),
    ]
    assert orders[1].order_id == "ORD-ENC-1-MOD-D2-K-sta"  # unchanged id for a plain lab
