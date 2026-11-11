"""Composition structure follows the country's profile, not the output
language, and the patient-instruction composer is a per-language choice
(Issue #3216).

``docs/design-guides/country-profile-spec.md`` §5: the Composition builders
take the country, so a country whose profile does not apply JP-CLINS gets the
generic Composition even when its output is Japanese, and a country that does
gets the JP-CLINS document even in English. The tests swap the profile's
``fhir_profiles`` list and keep the language fixed.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

import clinosim.country_profile as cp
from clinosim.modules.output.fhir_r4.documents.composition import _build_composition
from clinosim.modules.output.fhir_r4.lib.dosage import (
    _PATIENT_INSTRUCTION_COMPOSERS,
    _compose_instruction_ja,
    _compose_instruction_timing,
)
from clinosim.modules.output.fhir_r4.lib.ecs_extensions import build_ecs_institution_extension
from clinosim.modules.output.fhir_r4.lib.jp_profiles import JP_RESOURCE_INSTANCE_IDENTIFIER_SYSTEM

pytestmark = pytest.mark.unit

_DISCHARGE_SUMMARY = "18842-5"


@pytest.fixture
def with_profiles(monkeypatch: pytest.MonkeyPatch) -> Callable[[tuple[str, ...]], None]:
    """Replace every country's ``fhir_profiles`` with the given list."""
    real = cp._profile

    def apply(names: tuple[str, ...]) -> None:
        monkeypatch.setattr(cp, "_profile", lambda code: real(code).model_copy(update={"fhir_profiles": names}))

    return apply


def _doc() -> dict:
    return {
        "document_id": "doc-ENC-TEST-01",
        "loinc_code": _DISCHARGE_SUMMARY,
        "patient_id": "PAT-001",
        "encounter_id": "ENC-TEST",
        "author_practitioner_id": "DR-001",
        "authored_datetime": "2026-01-15T10:00:00",
        "format_type": "composition",
        "narrative": {"sections": {"body": "本文"}},
    }


def _profiles(comp: dict) -> list[str]:
    return comp.get("meta", {}).get("profile", [])


def test_japanese_output_without_jp_clins_gets_the_generic_composition(with_profiles) -> None:
    with_profiles(())
    comp = _build_composition(_doc(), {"body": "本文"}, "ja", country="JP")
    assert not any("JP_Composition_eDischargeSummary" in p for p in _profiles(comp))
    assert comp["identifier"]["system"] != JP_RESOURCE_INSTANCE_IDENTIFIER_SYSTEM


def test_english_output_with_jp_clins_gets_the_jp_clins_composition(with_profiles) -> None:
    with_profiles(("jp_core", "jp_clins"))
    comp = _build_composition(_doc(), {"body": "body"}, "en", country="US")
    assert any("JP_Composition_eDischargeSummary" in p for p in _profiles(comp))
    assert comp["identifier"]["system"] == JP_RESOURCE_INSTANCE_IDENTIFIER_SYSTEM


def test_institution_number_is_the_given_countrys() -> None:
    from clinosim.modules.output.fhir_r4.lib.ecs_extensions import hospital_institution_code

    ext = build_ecs_institution_extension("JP")
    assert ext["valueIdentifier"]["value"] == hospital_institution_code("JP")


def test_patient_instruction_composer_is_chosen_by_output_language() -> None:
    assert _PATIENT_INSTRUCTION_COMPOSERS["ja"] is _compose_instruction_ja
    assert "en" not in _PATIENT_INSTRUCTION_COMPOSERS  # the timing phrase is the default
    assert _compose_instruction_timing("PO", "qhs", None) == "at bedtime"
    assert _compose_instruction_timing("PO", "", 1) == ""
    assert _compose_instruction_ja("経口", "qd", None)
