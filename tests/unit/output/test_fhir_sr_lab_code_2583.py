"""Lab ServiceRequests carry a code and a readable text (Issue #2583)."""

from __future__ import annotations

from datetime import datetime

import pytest

from clinosim.modules.output.fhir_r4.labs.service_request import _build_standalone_sr
from clinosim.types.encounter import Order, OrderStatus, OrderType

pytestmark = pytest.mark.unit


def _sr(name: str, country: str = "us") -> dict:
    order = Order(
        order_id=f"ORD-ENC-1-{name}",
        encounter_id="ENC-1",
        patient_id="pt-1",
        order_type=OrderType.LAB,
        order_code=name,
        display_name=name,
        ordered_datetime=datetime(2025, 3, 1, 9, 0),
        status=OrderStatus.RESULTED,
    )
    return _build_standalone_sr(order, "ja" if country == "jp" else "en", country)


@pytest.mark.parametrize(
    ("name", "code", "text"),
    [
        ("K_stat", "2823-3", "K"),
        ("Sputum_culture", "6460-0", "sputum culture"),
        ("Basic_metabolic_panel", "51990-0", "BMP"),
        ("Lipid_panel", "57698-3", "lipid panel"),
        ("Blood_culture_set_1", "600-7", "blood culture"),
        ("ANA", "8061-4", "ANA"),  # the unknown-condition autoimmune screen
        ("RF", "11572-5", "RF"),
    ],
)
def test_internal_order_names_get_the_loinc_code_and_a_readable_text(name: str, code: str, text: str) -> None:
    sr = _sr(name)
    assert [c["code"] for c in sr["code"]["coding"]] == [code]
    assert sr["code"]["text"] == text
