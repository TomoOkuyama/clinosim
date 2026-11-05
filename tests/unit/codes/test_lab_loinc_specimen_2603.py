"""Issue #2603: lab LOINC codes name the specimen the test is run on."""

from __future__ import annotations

import pytest

from clinosim.codes import display as registry_display
from clinosim.locale.loader import load_code_mapping
from clinosim.modules.order.panel_grouping import load_panel_definitions
from clinosim.modules.output.fhir_r4.labs.coding_strategy import lab_loinc

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("panel", "code", "display"),
    [
        ("ABG", "24336-0", "Gas panel - Arterial blood"),
        ("BMP", "24321-2", "Basic metabolic 2000 panel - Serum or Plasma"),
    ],
)
def test_panel_codes_name_their_specimen(panel: str, code: str, display: str) -> None:
    assert load_panel_definitions()[panel]["loinc"] == code
    assert registry_display("loinc", code, "en") == display


def test_bnp_is_the_serum_or_plasma_assay() -> None:
    assert load_code_mapping("lab", "US")["BNP"] == "30934-4"
    assert registry_display("loinc", "30934-4", "en") == "Natriuretic peptide B [Mass/volume] in Serum or Plasma"


def test_bicarbonate_of_a_blood_gas_is_the_arterial_one() -> None:
    assert lab_loinc("HCO3", {"panel_key": "ABG"}) == "1960-4"
    assert registry_display("loinc", "1960-4", "en") == "Bicarbonate [Moles/volume] in Arterial blood"
    assert lab_loinc("HCO3", {"panel_key": "BMP"}) == "1963-8"
    assert lab_loinc("HCO3", {}) == "1963-8"
