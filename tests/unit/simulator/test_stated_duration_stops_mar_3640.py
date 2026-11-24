"""Issue #3640: an order with a stated duration is given for that duration and
then ends, whether the duration is a numeric field or the "xN days" of the
dose text."""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from types import SimpleNamespace

import numpy as np
import pytest

from clinosim.modules.order.engine import enrich_medication_order, parse_dose_string, protocol_medication_orders
from clinosim.simulator.medication_pipeline import _generate_mar
from clinosim.types.encounter import Order, OrderStatus, OrderType
from clinosim.types.staff import StaffRoster

pytestmark = pytest.mark.unit

_ADM = datetime(2024, 4, 5, 9, 0)


def _order(dose: str, *, duration_days: int | None = None, name: str = "Prednisolone") -> Order:
    order = Order(
        order_id="ORD-E1-ADM-S02",
        encounter_id="E1",
        patient_id="P1",
        order_type=OrderType.MEDICATION,
        display_name=name,
        ordered_datetime=_ADM + timedelta(hours=2),
        status=OrderStatus.PLACED,
        duration_days=duration_days,
    )
    return enrich_medication_order(order, dose)


def _days_given(order: Order, stay_days: int) -> list[int]:
    patient = SimpleNamespace(patient_id="P1", current_medications=[], age=70, baseline_vitals=None)
    days: list[int] = []
    for day in range(stay_days):
        if _generate_mar(patient, [order], day, _ADM, roster=StaffRoster(), rng=np.random.default_rng(day)):
            days.append(day)
    return days


def test_numeric_duration_stops_a_daily_order() -> None:
    assert _days_given(_order("40mg PO daily", duration_days=5), 14) == [0, 1, 2, 3, 4]


def test_order_without_duration_runs_to_discharge() -> None:
    assert _days_given(_order("40mg PO daily"), 14) == list(range(14))


@pytest.mark.parametrize(
    ("text", "days"),
    [
        ("Prednisolone 40mg PO daily x5 days", 5),
        ("30-40mg PO daily x5-7 days", 7),
        ("1g IV daily x 7 days", 7),
        ("50mcg IV bolus, then 50mcg/h continuous infusion x 3-5 days", 5),
        ("100mg IV daily x3 days", 3),
    ],
)
def test_duration_is_parsed_from_the_dose_text(text: str, days: int) -> None:
    assert parse_dose_string(text)["duration_days"] == days


@pytest.mark.parametrize("text", ["40mg PO daily", "15mg PO BID x21 days, then 20mg PO daily", "Max 5 days"])
def test_no_duration_when_the_text_states_none_or_continues_after(text: str) -> None:
    assert "duration_days" not in parse_dose_string(text)


def test_text_duration_stops_the_order() -> None:
    order = _order("Prednisolone 40mg PO daily x5 days")
    assert order.duration_days == 5
    assert _days_given(order, 14) == [0, 1, 2, 3, 4]


def test_explicit_numeric_duration_wins_over_the_text() -> None:
    assert _order("40mg PO daily x5 days", duration_days=3).duration_days == 3


def test_protocol_entry_gets_its_duration_from_the_text() -> None:
    (order,) = protocol_medication_orders(
        {"drug_id": "thiamine", "dose": "100mg IV daily x3 days", "route": "IV"},
        order_id="O1",
        encounter_id="E1",
        patient_id="P1",
        country="US",
        ordered_datetime=_ADM,
        ordered_by="DR",
    )
    assert order.duration_days == 3


def test_every_xn_days_token_in_disease_yaml_gives_a_duration() -> None:
    """Drift guard: a course length written in a protocol's dose / detail text
    is never left to free text."""
    from pathlib import Path

    import yaml

    root = Path(__file__).resolve().parents[3] / "clinosim" / "modules" / "disease" / "reference_data"
    token = re.compile(r"\bx\s*\d+(?:\s*-\s*\d+)?\s*days?\b", re.IGNORECASE)
    missing: list[str] = []

    def walk(node: object, where: str) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key in ("dose", "detail") and isinstance(value, str) and token.search(value):
                    if "duration_days" not in parse_dose_string(value) and not re.search(
                        r"x\s*\d+(?:\s*-\s*\d+)?\s*days?.*\bthen\b", value, re.I
                    ):
                        missing.append(f"{where}: {value}")
                walk(value, where)
        elif isinstance(node, list):
            for item in node:
                walk(item, where)

    for path in sorted(root.glob("*.yaml")):
        walk(yaml.safe_load(path.read_text()), path.name)
    assert not missing
