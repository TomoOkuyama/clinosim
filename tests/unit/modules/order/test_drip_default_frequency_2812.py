"""Issue #2812: a continuous infusion without a frequency token runs
continuously; it does not take the once-daily default."""

from __future__ import annotations

from datetime import datetime

import pytest

from clinosim.modules.order.engine import enrich_medication_order
from clinosim.types.encounter import Order, OrderStatus, OrderType

pytestmark = pytest.mark.unit


def _enrich(name: str, dose: str = "") -> Order:
    order = Order(
        order_id="ORD-1",
        encounter_id="ENC-1",
        patient_id="P1",
        order_type=OrderType.MEDICATION,
        display_name=name,
        ordered_datetime=datetime(2025, 1, 1, 9, 0),
        status=OrderStatus.PLACED,
    )
    return enrich_medication_order(order, dose)


@pytest.mark.parametrize(
    ("name", "dose"),
    [("Nitroglycerin", "5-10ug/min IV, titrate"), ("IV_fluid: Lactated Ringer 125 mL/h", "")],
)
def test_an_infusion_rate_without_a_frequency_is_continuous(name: str, dose: str) -> None:
    order = _enrich(name, dose)
    assert order.frequency == "CONTINUOUS"
    assert order.frequency_per_day == 24


def test_a_dose_without_a_frequency_is_still_daily() -> None:
    order = _enrich("Furosemide", "40mg IV")
    assert (order.frequency, order.frequency_per_day) == ("DAILY", 1)


def test_a_product_order_with_a_rate_unit_is_continuous() -> None:
    """The order was renamed to its product; only dose_unit carries the rate."""
    order = Order(
        order_id="ORD-2",
        encounter_id="ENC-1",
        patient_id="P1",
        order_type=OrderType.MEDICATION,
        display_name="Lactated Ringer solution",
        ordered_datetime=datetime(2025, 1, 1, 9, 0),
        status=OrderStatus.PLACED,
        dose_quantity=500.0,
        dose_unit="mL/h",
    )
    enrich_medication_order(order)
    assert order.frequency == "CONTINUOUS"
