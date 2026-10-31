"""Issue #2293: one "is the patient on warfarin" decision for INR generation,
result flagging and the therapeutic reference range."""

from __future__ import annotations

from datetime import date, datetime
from types import SimpleNamespace

import pytest

from clinosim.codes.drugs import get_drug, names_drug
from clinosim.locale.loader import load_reference_ranges
from clinosim.modules.observation.engine import determine_flag, medications_in_effect, therapeutic_range
from clinosim.modules.output.fhir_r4.labs.observations import _medications_on_result_day
from clinosim.modules.physiology.engine import medication_flags_from_context
from clinosim.types.encounter import Order, OrderType
from clinosim.types.patient import HomeMedication

pytestmark = pytest.mark.unit

ADMIT = date(2026, 3, 1)


def _warfarin_order(day: int) -> Order:
    return Order(
        order_id="o1",
        order_type=OrderType.MEDICATION,
        display_name="Warfarin 5mg PO daily",
        ordered_datetime=datetime(2026, 3, 1 + day, 9, 0),
    )


@pytest.mark.parametrize("country", ["US", "JP"])
def test_in_hospital_warfarin_inr_is_judged_against_the_therapeutic_range(country: str) -> None:
    meds = medications_in_effect([], [_warfarin_order(0)], ADMIT, current_day=4)
    assert therapeutic_range("PT_INR", country, medications=meds, age=60) is not None
    assert determine_flag("PT_INR", 2.5, sex="M", country=country, medications=meds, age=60) is None
    # Without the in-hospital order the same value is high against the normal range.
    assert determine_flag("PT_INR", 2.5, sex="M", country=country, medications=[], age=60) == "H"


@pytest.mark.parametrize(
    ("home", "orders", "day", "expected"),
    [
        ([HomeMedication(drug_name="Warfarin 3mg PO")], [], 0, True),
        ([HomeMedication(drug_name="ワルファリン錠 1mg")], [], 0, True),
        ([HomeMedication(drug_name="Coumadin 5mg")], [], 0, True),
        ([], ["order"], 4, True),
        ([], ["order"], 2, False),  # inside the 3-day loading period
        ([HomeMedication(drug_name="Apixaban 5mg")], [], 0, False),
    ],
)
def test_physiology_flagging_and_fhir_paths_agree(home: list, orders: list, day: int, expected: bool) -> None:
    order_objs = [_warfarin_order(0) for _ in orders]
    patient = SimpleNamespace(current_medications=home)

    on_warfarin = medication_flags_from_context(patient, order_objs, ADMIT, day)["on_warfarin"]
    flag_meds = medications_in_effect(home, order_objs, ADMIT, day)
    order_dicts = [
        {"order_type": "medication", "display_name": o.display_name, "ordered_datetime": o.ordered_datetime.isoformat()}
        for o in order_objs
    ]
    fhir_meds = _medications_on_result_day(home, order_dicts, ADMIT, datetime(2026, 3, 1 + day, 8, 0).isoformat())

    assert on_warfarin is expected
    assert (therapeutic_range("PT_INR", "US", medications=flag_meds, age=60) is not None) is expected
    assert (therapeutic_range("PT_INR", "US", medications=fhir_meds, age=60) is not None) is expected


def test_therapeutic_range_drugs_are_catalog_ids() -> None:
    for country in ("US", "JP"):
        for rows in (load_reference_ranges(country).get("therapeutic_ranges") or {}).values():
            for row in rows:
                for drug_id in row.get("drugs") or []:
                    assert get_drug(drug_id) is not None, f"{country}: {drug_id!r} is not a catalog drug id"


def test_names_drug_uses_catalog_names_and_aliases() -> None:
    assert names_drug("warfarin", "warfarin")
    assert names_drug("ワルファリンK錠", "warfarin")
    assert names_drug("COUMADIN", "warfarin")
    assert not names_drug("", "warfarin")
    assert not names_drug("Heparin", "warfarin")


def test_a_discontinue_marker_is_not_an_order_to_give_the_drug() -> None:
    marker = Order(
        order_id="d1",
        order_type=OrderType.MEDICATION,
        display_name="DISCONTINUE: Warfarin",
        ordered_datetime=datetime(2026, 3, 1, 9, 0),
    )
    assert medications_in_effect([], [marker], ADMIT, current_day=5) == []
    patient = SimpleNamespace(current_medications=[])
    assert medication_flags_from_context(patient, [marker], ADMIT, 5)["on_warfarin"] is False
