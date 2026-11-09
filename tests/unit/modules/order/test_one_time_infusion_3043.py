"""Issue #3043: a dose written as a timed infusion with no repeat ("100mg IV
over 2h", "10% bolus then 60min infusion") is one dose, not a daily order;
alteplase is given once."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import numpy as np
import pytest
import yaml

from clinosim.modules.order.absolute_dose import is_one_time_infusion
from clinosim.modules.order.engine import enrich_medication_order
from clinosim.simulator.medication_pipeline import _generate_mar
from clinosim.types.encounter import Order, OrderStatus, OrderType
from clinosim.types.patient import PatientProfile

pytestmark = pytest.mark.unit

_ADMIT = datetime(2026, 3, 1, 9, 0)


class _StubRoster:
    members: list = []

    def get_by_role(self, role: str, department: str | None = None) -> list:
        return []


def _order(name: str, ordered: datetime = _ADMIT) -> Order:
    return enrich_medication_order(
        Order(
            order_id="ORD-ENC-1-ESC-D1-Alteplas",
            encounter_id="ENC-1",
            patient_id="P1",
            order_type=OrderType.MEDICATION,
            display_name=name,
            ordered_datetime=ordered,
            status=OrderStatus.PLACED,
        )
    )


def _given(order: Order, days: int) -> int:
    return sum(
        len(
            _generate_mar(
                PatientProfile(patient_id="P1"),
                [order],
                day,
                _ADMIT,
                roster=_StubRoster(),  # type: ignore[arg-type]
                rng=np.random.default_rng(0),
            )
        )
        for day in range(days)
    )


@pytest.mark.parametrize(
    "name",
    [
        "Alteplase 100mg IV over 2h",
        "Alteplase 0.6mg/kg IV over 2h (max 40mg)",
        "Alteplase 0.9 mg/kg IV (max 90mg), 10% bolus then 60min infusion",
        "Magnesium sulfate 2g IV over 20min",
    ],
)
def test_an_alteplase_order_yields_one_administration(name: str) -> None:
    order = _order(name)
    assert order.single_dose and order.frequency == "once" and order.frequency_per_day == 1
    assert _given(order, 8) == 1


@pytest.mark.parametrize(
    "name",
    [
        "Mannitol 200mL (20%) IV over 30min q6-8h",  # a repeated infusion
        "Amiodarone 150mg IV over 10min, then 1mg/min x6h, then 0.5mg/min",  # a drip follows
        "Alteplase 0.5-1mg/h via catheter x12-24h",  # catheter-directed infusion
        "Ceftriaxone 2g IV over 30min daily",
        "Amlodipine 5mg PO",
    ],
)
def test_repeated_or_continuous_infusions_are_not_one_time(name: str) -> None:
    assert not is_one_time_infusion(name)
    assert not _order(name).single_dose


def _disease_dose_strings() -> list[tuple[str, str]]:
    root = Path(__file__).resolve().parents[4] / "clinosim" / "modules" / "disease" / "reference_data"
    out: list[tuple[str, str]] = []

    def walk(node: object, where: str) -> None:
        if isinstance(node, dict):
            if node.get("drug_id") and isinstance(node.get("dose"), str):
                out.append((where, f"{node['drug_id']} {node['dose']}"))
            for v in node.values():
                walk(v, where)
        elif isinstance(node, list):
            for v in node:
                walk(v, where)

    for path in sorted(root.glob("*.yaml")):
        walk(yaml.safe_load(path.read_text(encoding="utf-8")), path.stem)
    return out


def test_no_thrombolytic_bolus_in_a_disease_protocol_becomes_a_daily_order() -> None:
    """Guard over once-only drugs: every alteplase entry of the disease
    protocols is either a one-time dose or a continuous infusion."""
    entries = [(where, text) for where, text in _disease_dose_strings() if text.startswith("alteplase ")]
    assert len(entries) >= 4
    for where, text in entries:
        order = _order(text)
        assert order.single_dose or order.frequency == "CONTINUOUS", (where, text, order.frequency)


def test_a_one_time_order_placed_on_the_last_stay_day_is_still_given() -> None:
    """A late-evening admission: the day-3 escalation order is timed
    "admission + 3 days + 10 h", the next calendar date, after the last stay
    day the daily MAR covers; it is given before discharge."""
    from datetime import timedelta

    from clinosim.simulator.medication_pipeline import missed_single_doses

    admit = datetime(2026, 2, 18, 17, 23)
    order = _order("Magnesium sulfate 2g IV over 20min", admit + timedelta(days=3, hours=10))
    daily = [
        m
        for day in range(4)
        for m in _generate_mar(
            PatientProfile(patient_id="P1"),
            [order],
            day,
            admit,
            roster=_StubRoster(),  # type: ignore[arg-type]
            rng=np.random.default_rng(0),
        )
    ]
    assert daily == []
    discharge = datetime(2026, 2, 22, 9, 23)
    caught = missed_single_doses(PatientProfile(patient_id="P1"), [order], daily, admit, discharge, roster=None)
    assert len(caught) == 1 and order.ordered_datetime <= caught[0].actual_datetime < discharge
    # A dose already given is not repeated, and none is given after discharge.
    assert missed_single_doses(PatientProfile(patient_id="P1"), [order], caught, admit, discharge, roster=None) == []
    assert (
        missed_single_doses(PatientProfile(patient_id="P1"), [order], [], admit, order.ordered_datetime, roster=None)
        == []
    )
