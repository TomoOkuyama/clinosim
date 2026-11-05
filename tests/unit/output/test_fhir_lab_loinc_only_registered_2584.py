"""An internal lab name never goes under the LOINC system (Issue #2584)."""

from __future__ import annotations

from datetime import datetime

import pytest

from clinosim.modules.output.fhir_r4.labs.coding_strategy import LegacyLOINCStrategy
from clinosim.modules.output.fhir_r4.labs.service_request import _build_standalone_sr
from clinosim.types.encounter import Order, OrderStatus, OrderType

pytestmark = pytest.mark.unit


def _sr(name: str, order_code: str, country: str = "us") -> dict:
    order = Order(
        order_id=f"ORD-ENC-1-{name}",
        encounter_id="ENC-1",
        patient_id="pt-1",
        order_type=OrderType.LAB,
        order_code=order_code,
        display_name=name,
        ordered_datetime=datetime(2025, 3, 1, 9, 0),
        status=OrderStatus.RESULTED,
    )
    return _build_standalone_sr(order, "ja" if country == "jp" else "en", country)


@pytest.mark.parametrize("country", ["us", "jp"])
def test_an_unresolvable_name_emits_text_only(country: str) -> None:
    sr = _sr("No_such_test", "No_such_test", country)
    assert "coding" not in sr["code"]
    assert sr["code"]["text"] == "No such test"


def test_a_registered_loinc_order_code_is_kept() -> None:
    sr = _sr("No_such_test", "2160-0")
    assert sr["code"]["coding"][0] == {**sr["code"]["coding"][0], "system": "http://loinc.org", "code": "2160-0"}


def test_us_observation_drops_an_internal_order_code() -> None:
    strategy = LegacyLOINCStrategy()
    assert (
        strategy.emit_codings(lab_name="No_such_test", order={"order_code": "No_such_test"}, result={}, country="US")
        == []
    )
    coded = strategy.emit_codings(lab_name="No_such_test", order={"order_code": "2160-0"}, result={}, country="US")
    assert [c["code"] for c in coded] == ["2160-0"]
