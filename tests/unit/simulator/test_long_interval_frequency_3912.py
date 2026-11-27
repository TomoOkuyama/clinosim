"""Long-interval dosing frequencies (Issue #3912).

A continued home denosumab ("60mg SC q6months") had no frequency token, so the
inpatient order fell back to DAILY and was given on every hospital day (37
doses in two stays). A cadence the order engine does not know must never
become DAILY; a home medication due less often than any stay is carried on the
home-medication list, not ordered in the stay.
"""

from __future__ import annotations

import glob
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest
import yaml

import clinosim
from clinosim.modules.order.engine import (
    dosing_interval_days,
    enrich_medication_order,
    parse_dose_string,
    unrecognized_cadence,
)
from clinosim.simulator.medication_pipeline import _generate_home_medication_orders, _generate_mar
from clinosim.types.encounter import Order, OrderStatus, OrderType
from clinosim.types.patient import HomeMedication
from clinosim.types.staff import StaffRoster

pytestmark = pytest.mark.unit

_ADM = datetime(2025, 10, 10, 9, 0)


@pytest.mark.parametrize(
    ("label", "days"),
    [
        ("Q6MONTHS", 182),
        ("q6months", 182),
        ("every 6 months", 182),
        ("Q3MONTHS", 91),
        ("quarterly", 91),
        ("Q12MONTHS", 365),
        ("yearly", 365),
        ("annual", 365),
        ("WEEKLY", 7),
        ("MONTHLY", 30),
    ],
)
def test_long_interval_tokens_resolve_to_days(label: str, days: int) -> None:
    assert dosing_interval_days(label) == days


def test_q6months_dose_text_keeps_its_cadence_not_a_daily_default() -> None:
    assert parse_dose_string("60mg SC q6months")["frequency"] == "Q6MONTHS"
    order = Order(
        order_id="O1",
        encounter_id="E1",
        patient_id="P1",
        order_type=OrderType.MEDICATION,
        display_name="Denosumab",
        ordered_datetime=_ADM,
        status=OrderStatus.PLACED,
    )
    enrich_medication_order(order, "60mg SC q6months")
    assert order.frequency == "Q6MONTHS"
    assert order.frequency != "DAILY"


def _given(order: Order, days: int) -> list:
    patient = SimpleNamespace(patient_id="P1", current_medications=[], age=78, baseline_vitals=None)
    out: list = []
    for day in range(days):
        out += _generate_mar(patient, [order], day, _ADM, roster=StaffRoster(), rng=np.random.default_rng(day))
    return out


def test_a_protocol_ordered_denosumab_is_given_once_in_a_25_day_stay() -> None:
    order = Order(
        order_id="O1",
        encounter_id="E1",
        patient_id="P1",
        order_type=OrderType.MEDICATION,
        display_name="Denosumab",
        ordered_datetime=_ADM + timedelta(minutes=60),
        status=OrderStatus.PLACED,
        route="SC",
    )
    enrich_medication_order(order, "60mg SC q6months")
    assert len(_given(order, 25)) == 1


def _home_orders(patient_factory, *meds: HomeMedication) -> list[Order]:
    patient = patient_factory()
    patient.current_medications = list(meds)
    return _generate_home_medication_orders(
        patient,
        encounter_id="ENC-1",
        admission_time=_ADM,
        attending_id="PR-1",
        rng=np.random.default_rng(0),
        state=SimpleNamespace(renal_function=0.9),
    )[0]


def test_continued_home_denosumab_is_not_ordered_in_the_stay(patient_factory) -> None:
    denosumab = HomeMedication(drug_name="Denosumab", route="SC", dose="60mg SC q6months")
    assert [o.display_name for o in _home_orders(patient_factory, denosumab)] == []


def test_the_denosumab_stays_on_the_home_medication_list(patient_factory) -> None:
    patient = patient_factory()
    patient.current_medications = [HomeMedication(drug_name="Denosumab", route="SC", dose="60mg SC q6months")]
    _generate_home_medication_orders(
        patient,
        encounter_id="ENC-1",
        admission_time=_ADM,
        attending_id="PR-1",
        rng=np.random.default_rng(0),
        state=SimpleNamespace(renal_function=0.9),
    )
    assert [m.drug_name for m in patient.current_medications] == ["Denosumab"]


def test_weekly_and_monthly_home_medications_are_still_ordered(patient_factory) -> None:
    meds = (
        HomeMedication(drug_name="Alendronate", route="PO", dose="35mg", frequency="weekly"),
        HomeMedication(drug_name="Naltrexone", route="IM", dose="380mg", frequency="monthly"),
        HomeMedication(drug_name="Amlodipine", route="PO", dose="5mg", frequency="daily"),
    )
    assert [o.display_name for o in _home_orders(patient_factory, *meds)] == ["Alendronate", "Naltrexone", "Amlodipine"]


@pytest.mark.parametrize(
    ("dose", "per_day"),
    [("40-80mg IV q6-8h", 3), ("15-20mg/kg IV q8-12h", 2), ("0.5mg NEB q4-6h", 4), ("2.5mg NEB q1-4h", 6)],
)
def test_hour_range_cadence_is_given_at_its_longer_interval(dose: str, per_day: int) -> None:
    parsed = parse_dose_string(dose)
    assert parsed["frequency_per_day"] == per_day
    assert parsed["frequency"].startswith("Q")


def test_a_protocol_bolus_series_is_one_bolus_not_a_scheduled_order() -> None:
    from clinosim.modules.order.engine import protocol_medication_orders

    spec = {"drug_id": "labetalol", "dose": "10-20mg IV bolus q10-20min, max 300mg", "route": "IV"}
    (order,) = protocol_medication_orders(
        spec,
        order_id="O1",
        encounter_id="E1",
        patient_id="P1",
        country="us",
        ordered_datetime=_ADM,
        ordered_by="DR-1",
    )
    assert (order.single_dose, order.frequency_per_day) == (True, 1)
    assert len(_given(order, 5)) == 1


def test_a_cadence_the_engine_does_not_know_never_becomes_daily() -> None:
    assert unrecognized_cadence("10mg PO q7fortnights") is not None
    order = Order(
        order_id="O1",
        encounter_id="E1",
        patient_id="P1",
        order_type=OrderType.MEDICATION,
        display_name="Somedrug",
        ordered_datetime=_ADM,
        status=OrderStatus.PLACED,
    )
    with pytest.raises(ValueError, match="q7fortnights"):
        enrich_medication_order(order, "10mg PO q7fortnights")


# --- guard: every frequency string in the drug data is recognized ----------------

_DRUG_KEYS = ("drug", "drug_id", "drug_name")
_STRING_KEYS = ("dose", "frequency", "default_dose", "default_frequency")


def _drug_strings(node: Any, where: str):
    if isinstance(node, dict):
        if any(k in node for k in _DRUG_KEYS):
            for key in _STRING_KEYS:
                if isinstance(node.get(key), str):
                    yield where, key, node[key]
        for k, v in node.items():
            yield from _drug_strings(v, where)
    elif isinstance(node, list):
        for v in node:
            yield from _drug_strings(v, where)


def test_every_frequency_in_the_drug_data_is_recognized() -> None:
    root = Path(clinosim.__file__).parent
    seen = 0
    bad: list[str] = []
    for path in sorted(glob.glob(str(root / "**" / "*.yaml"), recursive=True)):
        try:
            data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        except yaml.YAMLError:
            continue
        for where, key, text in _drug_strings(data, path):
            seen += 1
            token = unrecognized_cadence(text)
            if token is not None:
                bad.append(f"{Path(where).name} {key}={text!r}: {token}")
    assert seen > 500, "the walk found no drug entries"
    assert not bad, "frequency strings the order engine cannot resolve (they would be given DAILY):\n" + "\n".join(bad)


def test_the_token_table_is_well_formed() -> None:
    from clinosim.locale.loader import load_frequency_tokens

    for token, (freq, period, unit) in load_frequency_tokens().items():
        assert freq >= 1 and period >= 1 and unit in {"d", "wk", "mo", "a"}, token
