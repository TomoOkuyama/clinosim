"""Issue #3232: the hyperkalemia response records the dextrose given with the
insulin as its own administration, holds digoxin while the potassium is at or
above the treatment threshold, and writes the hold reason from the latest
potassium resulted before each dose (not the first triggering value)."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime

import numpy as np
import pytest

from clinosim.codes.drugs import drug_ref, jp_drug_code
from clinosim.modules.drug_safety.hyperkalemia import (
    holds_for_hyperkalemia,
    holds_while_hyperkalemic,
    hyperkalemia_treatment_orders,
    potassium_history,
    potassium_hold_from_results,
)
from clinosim.modules.order.engine import parse_dose_string
from clinosim.simulator.medication_pipeline import _generate_mar
from clinosim.types.encounter import Order, OrderResult, OrderStatus, OrderType
from clinosim.types.patient import PatientProfile

pytestmark = pytest.mark.unit

_ADMIT = datetime(2026, 3, 1, 14, 0)


class _StubRoster:
    members: list = []

    def get_by_role(self, role: str, department: str | None = None) -> list:
        return []


def _order(order_id: str, drug: str) -> Order:
    return Order(
        order_id=order_id,
        encounter_id="ENC-3232",
        patient_id="POP-3232",
        order_type=OrderType.MEDICATION,
        display_name=drug,
        ordered_datetime=_ADMIT,
        status=OrderStatus.PLACED,
        route="PO",
        frequency_per_day=1,
    )


def _k(value: float, at: datetime) -> OrderResult:
    return OrderResult(result_datetime=at, lab_name="K", value=value, unit="mmol/L", flag="H")


def _mar(orders: list[Order], day: int, results: list[OrderResult]):
    hold = potassium_hold_from_results(results)
    assert hold is not None
    hold = replace(hold, history=potassium_history(results))
    return _generate_mar(
        PatientProfile(patient_id="POP-3232"),
        orders,
        day,
        _ADMIT,
        roster=_StubRoster(),  # type: ignore[arg-type]
        rng=np.random.default_rng(0),
        potassium_hold=hold,
    )


@pytest.mark.parametrize("country", ["US", "JP"])
def test_dextrose_is_ordered_with_the_insulin(country: str) -> None:
    hold = potassium_hold_from_results([_k(6.9, datetime(2026, 3, 2, 6, 30))])
    assert hold is not None
    orders = hyperkalemia_treatment_orders(
        hold, patient_id="POP-3232", encounter_id="ENC-3232", country=country, day=1, parse_dose=parse_dose_string
    )
    ids = [drug_ref(o.display_name) for o in orders]
    assert "insulin_regular_human" in ids and "dextrose_50" in ids
    dextrose = orders[ids.index("dextrose_50")]
    assert dextrose.single_dose and dextrose.order_id.endswith("-HYPERK-D1-dextrose-50")
    assert "50 mL" in dextrose.display_name
    # The dose is the 50 mL volume, not the 50% strength in the drug name.
    assert (dextrose.dose_quantity, dextrose.dose_unit, dextrose.route) == (50.0, "mL", "IV")
    # Given once, on the day ordered, like the insulin.
    mars = _generate_mar(
        PatientProfile(patient_id="POP-3232"),
        orders,
        1,
        _ADMIT,
        roster=_StubRoster(),  # type: ignore[arg-type]
        rng=np.random.default_rng(0),
        potassium_hold=hold,
    )
    assert any(m.order_id == dextrose.order_id and m.status in ("given", "refused") for m in mars)
    # A persisting hyperkalemia does not repeat the dextrose (it goes with the insulin).
    again = hyperkalemia_treatment_orders(
        hold, patient_id="POP-3232", encounter_id="ENC-3232", country=country, day=2, continuing=True
    )
    assert "dextrose_50" not in {drug_ref(o.display_name) for o in again}


def test_dextrose_has_a_jp_product_code() -> None:
    assert jp_drug_code("dextrose_50", "IV") == "3231401H7023"


def test_digoxin_is_held_only_while_the_potassium_is_high() -> None:
    assert holds_while_hyperkalemic("digoxin")
    assert not holds_for_hyperkalemia("digoxin")  # not a stay-long hold
    assert not holds_while_hyperkalemic("candesartan")
    results = [_k(6.9, datetime(2026, 3, 2, 6, 30)), _k(5.1, datetime(2026, 3, 3, 6, 30))]
    digoxin = _order("ORD-DIG", "Digoxin 0.25mg")
    held = [m for m in _mar([digoxin], 1, results[:1]) if m.status == "held"]
    assert held and held[0].hold_reason == "K 6.9 mmol/L"
    # The next morning's potassium is below the threshold: digoxin resumes.
    assert all(m.status != "held" for m in _mar([digoxin], 2, results))


def test_the_hold_reason_follows_the_latest_potassium() -> None:
    results = [
        _k(8.3, datetime(2026, 3, 2, 6, 30)),
        _k(5.4, datetime(2026, 3, 3, 6, 30)),
        _k(4.9, datetime(2026, 3, 4, 6, 30)),
    ]
    candesartan = _order("ORD-CAN", "Candesartan 8mg")
    reasons = {d: {m.hold_reason for m in _mar([candesartan], d, results)} for d in (1, 2, 3)}
    assert reasons == {1: {"K 8.3 mmol/L"}, 2: {"K 5.4 mmol/L"}, 3: {"K 4.9 mmol/L"}}


@pytest.mark.parametrize(
    ("order", "ja"),
    [
        ("Dextrose 50% 50 mL IV", "50%ブドウ糖液 50 mL 静注"),
        ("4-Factor PCC (Kcentra) 2000 units IV", "乾燥濃縮人プロトロンビン複合体 2000 単位 静注"),
        ("Calcium Gluconate 10 mL IV", "グルコン酸カルシウム 10 mL 静注"),
    ],
)
def test_a_drug_name_ending_in_a_symbol_is_localized_inside_an_order(order: str, ja: str) -> None:
    from clinosim.locale.free_text import localize_drug_name

    assert localize_drug_name(order, "ja") == ja
    assert localize_drug_name(order, "en") == order
