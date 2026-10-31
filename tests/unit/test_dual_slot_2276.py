"""Issue #2276: one registry of English-only CodeSystems and one dual-slot
CodeableConcept builder."""

from __future__ import annotations

import pytest

from clinosim.codes import ENGLISH_ONLY_SYSTEM_PREFIXES, get_system_uri, is_english_only_system
from clinosim.codes import display as registry_display
from clinosim.modules.output.fhir_r4.encounters.encounter import _build_hosp_concept
from clinosim.modules.output.fhir_r4.lib.common import dual_slot_concept
from clinosim.modules.output.fhir_r4.post_process.strip import _ENGLISH_ONLY_CODING_SYSTEM_PREFIXES

pytestmark = pytest.mark.unit


def test_one_registry_accepts_keys_and_uris() -> None:
    assert _ENGLISH_ONLY_CODING_SYSTEM_PREFIXES is ENGLISH_ONLY_SYSTEM_PREFIXES
    assert is_english_only_system("hl7-discharge-disposition")
    assert is_english_only_system(get_system_uri("loinc"))
    assert not is_english_only_system("jpfhir-doc-typecodes")
    assert not is_english_only_system("yj")


def test_english_only_system_jp_keeps_english_coding_and_japanese_text() -> None:
    concept = dual_slot_concept("hl7-discharge-disposition", "home", "ja")
    assert concept["coding"][0]["display"] == registry_display("hl7-discharge-disposition", "home", "en")
    assert concept["text"] == registry_display("hl7-discharge-disposition", "home", "ja")
    assert concept["text"] != concept["coding"][0]["display"]


def test_english_only_system_us_is_english_in_both_slots() -> None:
    concept = dual_slot_concept("hl7-discharge-disposition", "home", "en")
    assert concept["coding"][0]["display"] == concept["text"]


def test_jp_codesystem_keeps_japanese_coding_display() -> None:
    concept = dual_slot_concept("jpfhir-doc-typecodes", "64297-5", "ja")
    assert concept["coding"][0]["display"] == registry_display("jpfhir-doc-typecodes", "64297-5", "ja")


def test_unregistered_code_has_no_echoed_display() -> None:
    concept = dual_slot_concept("hl7-discharge-disposition", "not-a-code", "ja")
    assert "display" not in concept["coding"][0]
    assert "text" not in concept


def test_hospitalization_concept_uses_the_shared_builder() -> None:
    assert _build_hosp_concept("hl7-admit-source", "emd", "ja") == dual_slot_concept("hl7-admit-source", "emd", "ja")
