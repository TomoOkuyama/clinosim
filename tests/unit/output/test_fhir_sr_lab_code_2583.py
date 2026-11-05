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
        # Issue #2636: titled like the result (the coded display); a panel by its panel display.
        ("K_stat", "2823-3", "Potassium [Moles/volume] in Serum or Plasma"),
        ("Sputum_culture", "6460-0", "Bacteria identified in Sputum by Culture"),
        ("Basic_metabolic_panel", "24321-2", "Basic metabolic 2000 panel - Serum or Plasma"),
        ("Lipid_panel", "57698-3", "Lipid panel with direct LDL - Serum or Plasma"),
        ("Blood_culture_set_1", "600-7", "Bacteria identified in Blood by Culture"),
        ("ANA", "8061-4", "Nuclear Ab [Presence] in Serum"),  # the unknown-condition autoimmune screen
        ("RF", "11572-5", "Rheumatoid factor [Units/volume] in Serum or Plasma"),
    ],
)
def test_internal_order_names_get_the_loinc_code_and_a_readable_text(name: str, code: str, text: str) -> None:
    sr = _sr(name)
    assert [c["code"] for c in sr["code"]["coding"]] == [code]
    assert sr["code"]["text"] == text
