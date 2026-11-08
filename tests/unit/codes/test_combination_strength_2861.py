"""Combination strengths are parsed and coded as one product (Issue #2861)."""

from __future__ import annotations

import pytest

from clinosim.codes.drugs import rxnorm_scd_code
from clinosim.modules.order.engine import parse_dose_string

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("text", "dose"),
    [
        ("Amoxicillin/clavulanate 875/125mg", 875.0),
        ("Trimethoprim/Sulfamethoxazole 160/800mg PO bid", 160.0),
        ("Buprenorphine/Naloxone 8mg/2mg", 8.0),
        ("Ibuprofen 400mg", 400.0),
    ],
)
def test_combination_dose_is_the_first_ingredient(text: str, dose: float) -> None:
    assert parse_dose_string(text)["dose_quantity"] == dose


def test_amoxicillin_clavulanate_875_125_is_its_own_scd() -> None:
    # RxNorm 562508 = amoxicillin 875 MG / clavulanate 125 MG Oral Tablet (RxNav).
    assert rxnorm_scd_code("Amoxicillin/clavulanate", "PO", 875, "mg") == "562508"


def test_ingredient_order_different_from_rxnorm_still_matches() -> None:
    # RxNorm 198335 = sulfamethoxazole 800 MG / trimethoprim 160 MG Oral Tablet.
    assert rxnorm_scd_code("Trimethoprim/Sulfamethoxazole", "PO", 160, "mg") == "198335"
    assert rxnorm_scd_code("Trimethoprim/Sulfamethoxazole", "PO", 800, "mg") == "198335"
