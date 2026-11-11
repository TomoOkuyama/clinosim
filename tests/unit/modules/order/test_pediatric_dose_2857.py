"""Children get weight-based ED doses (Issue #2857)."""

from __future__ import annotations

import pytest

from clinosim.modules.order.pediatric_dose import pediatric_order_name

pytestmark = pytest.mark.unit


def test_acetaminophen_is_15_mg_per_kg_for_an_infant() -> None:
    assert pediatric_order_name("Acetaminophen 500mg", 5, 7.0, country="US") == "Acetaminophen 105mg"


def test_dose_is_capped_at_the_maximum() -> None:
    assert pediatric_order_name("Ondansetron 4mg IV", 120, 35.0, country="US") == "Ondansetron 4mg IV"


def test_small_doses_keep_one_decimal() -> None:
    assert pediatric_order_name("Ondansetron 4mg IV", 12, 9.1, country="US") == "Ondansetron 1.4mg IV"


def test_below_minimum_age_the_drug_is_not_given() -> None:
    assert pediatric_order_name("Ibuprofen 400mg", 3, 6.0, country="US") is None
    assert pediatric_order_name("Ketorolac 30mg IV", 5, 7.0, country="US") is None


def test_adults_and_unlisted_drugs_are_unchanged() -> None:
    assert pediatric_order_name("Acetaminophen 500mg", 240, 70.0, country="US") == "Acetaminophen 500mg"
    assert pediatric_order_name("Cefazolin 1g IV", 60, 18.0, country="US") == "Cefazolin 1g IV"
