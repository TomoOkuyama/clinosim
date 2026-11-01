"""The order, not the drug name, decides the IV infusion mode (Issue #2436)."""

from __future__ import annotations

import pytest

from clinosim.modules.disease.protocol import _NAME_ONLY_DRUG_EXEMPT
from clinosim.modules.output.fhir_r4.lib.common import augment_iv_dosage_with_rate

pytestmark = pytest.mark.unit


def _augment(display: str, frequency: str, drug_id: str = "insulin_regular_human") -> dict:
    dosage: dict = {"text": display}
    augment_iv_dosage_with_rate(
        dosage, dose_text="0.1U", route="IV", display_name=display, drug_id=drug_id, frequency=frequency
    )
    return dosage


def test_continuous_order_gets_the_drip_rate_whatever_the_name() -> None:
    dosage = _augment("Insulin, Regular, Human 0.1U", "CONTINUOUS")
    assert dosage["doseAndRate"][0]["rateQuantity"]["value"] == 0.1
    assert "timing" not in dosage


def test_one_off_iv_dose_of_a_drip_drug_gets_no_drip_rate() -> None:
    dosage = _augment("Insulin, Regular, Human 10 units IV", "ONCE")
    assert "doseAndRate" not in dosage


def test_no_name_only_exemption_left() -> None:
    assert not _NAME_ONLY_DRUG_EXEMPT
