"""JP osteoporosis patients get an active vitamin D3 analogue (Issue #2353).

Japan has no prescription cholecalciferol, so the former JP ``Vitamin D 1000IU``
order had no YJ product and was emitted uncoded (after it had been coded as an
alfacalcidol product under the wrong drug name).
"""

from __future__ import annotations

import pytest

from clinosim.codes.drugs import jp_drug_code
from clinosim.modules.output.fhir_r4.medications.medications import _resolve_medication_concept
from clinosim.modules.patient.activator import _derive_home_medications
from clinosim.types.patient import ChronicCondition

pytestmark = pytest.mark.unit


def _names(country: str) -> list[str]:
    meds = _derive_home_medications(
        [ChronicCondition(code="M81", severity_score=0.5)], patient_id="P1", country=country, patient_age=70
    )
    return [m.drug_name.lower() for m in meds]


def test_jp_gets_alfacalcidol_and_no_cholecalciferol() -> None:
    names = _names("JP")
    assert "alfacalcidol" in names
    assert "vitamin d" not in names


def test_us_keeps_cholecalciferol() -> None:
    names = _names("US")
    assert "vitamin d" in names
    assert "alfacalcidol" not in names


def test_jp_alfacalcidol_is_coded() -> None:
    assert jp_drug_code("alfacalcidol", "PO") == "3112001M3065"  # アルファロールカプセル1μg
    concept, _ = _resolve_medication_concept("Alfacalcidol", order_code="", country="JP", route="PO")
    assert concept["coding"][0]["code"] == "3112001M3065"
