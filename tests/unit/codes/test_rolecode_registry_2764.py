"""Issue #2764: v3-RoleCode relationship codes are registered and displayed from the registry."""

from __future__ import annotations

import pytest

from clinosim.codes import code_exists
from clinosim.codes import display as registry_display
from clinosim.modules.output.fhir_r4.demographics.family_history import _build_relationship_codeable

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("code", "en", "ja"), [("MTH", "mother", "母"), ("FTH", "father", "父"), ("NSIB", "natural sibling", "兄弟姉妹")]
)
def test_relationship_codes_are_registered_with_the_hl7_display(code: str, en: str, ja: str) -> None:
    assert code_exists("hl7-v3-rolecode", code, exact=True)
    assert registry_display("hl7-v3-rolecode", code, "en") == en  # tx.fhir.org $lookup display
    assert registry_display("hl7-v3-rolecode", code, "ja") == ja


def test_relationship_concept_is_english_coding_plus_localized_text() -> None:
    assert _build_relationship_codeable("FTH", "en") == {
        "coding": [{"system": "http://terminology.hl7.org/CodeSystem/v3-RoleCode", "code": "FTH", "display": "father"}]
    }
    assert _build_relationship_codeable("FTH", "ja")["text"] == "父"
