"""English-only codings are built with system_coding / dual_slot_concept (Issue #2337)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from clinosim.modules.output.fhir_r4.lib.common import dual_slot_concept, survey_category

pytestmark = pytest.mark.unit

_FHIR = Path(__file__).resolve().parents[3] / "clinosim" / "modules" / "output" / "fhir_r4"


def _sources() -> list[tuple[str, str]]:
    return [(str(p.relative_to(_FHIR)), p.read_text(encoding="utf-8")) for p in _FHIR.rglob("*.py")]


def test_the_legacy_helpers_are_gone() -> None:
    pattern = re.compile(r"\b_coding_with_display\b|(?<![\w.])_value\(")
    assert not [name for name, src in _sources() if pattern.search(src)]


@pytest.mark.parametrize("system_key", ["hl7-observation-category", "hl7-condition-category", "hl7-organization-type"])
def test_no_hand_built_hl7_category_coding(system_key: str) -> None:
    hand_built = re.compile(r'"system": get_system_uri\("' + re.escape(system_key) + r'"\)')
    assert not [name for name, src in _sources() if hand_built.search(src)]


def test_jp_concept_keeps_english_coding_and_japanese_text() -> None:
    concept = dual_slot_concept("hl7-organization-type", "pay", "ja")
    assert concept["coding"][0]["display"] == "Payer"
    assert concept["text"] == "保険者"
    assert survey_category("ja")[0]["coding"][0]["display"] == "Survey"


def test_jp_condition_status_has_japanese_text() -> None:
    concept = dual_slot_concept("hl7-condition-clinical", "active", "ja")
    assert concept["coding"][0]["display"] == "Active"
    assert concept["text"] and concept["text"] != "Active"
