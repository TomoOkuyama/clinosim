"""Issue #2982: a non-daily medication order is given on its own cadence in hospital.

A continued home medication "Alendronate 35mg PO WEEKLY" used to fall back to
the three-times-a-day PO default of the MAR (no per-day frequency), so it was
given up to three times a day. A weekly order is now given on the day it is
ordered and every seventh day after; alendronate is held for renal
impairment (not recommended at CrCl < 35 mL/min, FDA label).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

import numpy as np
import pytest

from clinosim.modules.order.engine import enrich_medication_order, parse_dose_string
from clinosim.simulator.medication_pipeline import _generate_mar, renal_medication_rules
from clinosim.types.encounter import Order, OrderStatus, OrderType
from clinosim.types.staff import StaffRoster

pytestmark = pytest.mark.unit

_ADM = datetime(2024, 4, 5, 13, 30)


def _order(frequency: str, dose: str, name: str = "Alendronate", route: str = "PO") -> Order:
    order = Order(
        order_id="ORD-E1-HM-03",
        encounter_id="E1",
        patient_id="P1",
        order_type=OrderType.MEDICATION,
        display_name=name,
        ordered_datetime=_ADM + timedelta(minutes=60),
        status=OrderStatus.PLACED,
        route=route,
        frequency=frequency,
    )
    return enrich_medication_order(order, dose)


def _given(order: Order, days: int) -> list:
    patient = SimpleNamespace(patient_id="P1", current_medications=[], age=78, baseline_vitals=None)
    out: list = []
    for day in range(days):
        out += _generate_mar(patient, [order], day, _ADM, roster=StaffRoster(), rng=np.random.default_rng(day))
    return out


def test_weekly_order_yields_one_administration_in_a_5_day_stay() -> None:
    assert len(_given(_order("WEEKLY", "35mg"), 5)) == 1


def test_weekly_order_is_given_every_seventh_day() -> None:
    doses = sorted(m.scheduled_datetime for m in _given(_order("WEEKLY", "35mg"), 15))
    assert [d.date() for d in doses] == [(_ADM + timedelta(days=n)).date() for n in (0, 7, 14)]


def test_monthly_injection_is_given_once_in_a_two_week_stay() -> None:
    assert len(_given(_order("MONTHLY", "380mg", name="Naltrexone", route="IM"), 14)) == 1


def test_weekly_dose_text_is_not_turned_into_a_daily_order() -> None:
    assert parse_dose_string("70mg PO weekly")["frequency"] == "WEEKLY"
    order = _order("", "70mg PO weekly")
    assert (order.frequency, order.frequency_per_day) == ("WEEKLY", None)


def test_daily_order_is_unchanged() -> None:
    assert len(_given(_order("DAILY", "10mg", name="Amlodipine"), 3)) == 3


def test_alendronate_is_held_for_renal_impairment() -> None:
    assert renal_medication_rules()["alendronate"] == "hold"
