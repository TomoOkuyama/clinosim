"""Guard: repeated JP profile / identifier-system URIs are single constants (#2842).

``docs/design-guides/implementation-rules.md`` §4 — a profile or identifier
URI used in more than one place is one module-level constant. Each URI in
``clinosim/modules/output/fhir_r4/lib/jp_profiles.py`` must (1) equal its
spec value and (2) appear as a string literal in no other Python source file
under ``clinosim/``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from clinosim.modules.output.fhir_r4.lib import jp_profiles

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SOURCE_ROOT = _REPO_ROOT / "clinosim"
_CONSTANTS_FILE = Path(jp_profiles.__file__).resolve()

# Spec values (JP Core / JP-CLINS fixedUri / canonical URLs).
_EXPECTED = {
    "JP_INSURANCE_MEDICAL_INSTITUTION_NO_SYSTEM": "http://jpfhir.jp/fhir/core/IdSystem/insurance-medical-institution-no",
    "JP_RESOURCE_INSTANCE_IDENTIFIER_SYSTEM": "http://jpfhir.jp/fhir/core/IdSystem/resourceInstance-identifier",
    "JP_MEDICATION_RP_GROUP_NUMBER_SYSTEM": "http://jpfhir.jp/fhir/core/mhlw/IdSystem/Medication-RPGroupNumber",
    "JP_MEDICATION_ADMINISTRATION_INDEX_SYSTEM": "http://jpfhir.jp/fhir/core/mhlw/IdSystem/MedicationAdministrationIndex",
    "JP_OBSERVATION_COMMON_PROFILE": "http://jpfhir.jp/fhir/core/StructureDefinition/JP_Observation_Common",
    "JP_LOCATION_PROFILE": "http://jpfhir.jp/fhir/core/StructureDefinition/JP_Location",
    "JP_ORGANIZATION_PROFILE": "http://jpfhir.jp/fhir/core/StructureDefinition/JP_Organization",
    "JP_ORGANIZATION_ECS_PROFILE": "http://jpfhir.jp/fhir/eCS/StructureDefinition/JP_Organization_eCS",
    "JP_PROCEDURE_PROFILE": "http://jpfhir.jp/fhir/core/StructureDefinition/JP_Procedure",
    "JP_COMPOSITION_EDISCHARGE_SUMMARY_PROFILE": (
        "http://jpfhir.jp/fhir/eDischargeSummary/StructureDefinition/JP_Composition_eDischargeSummary"
    ),
}


def test_exported_constants_match_expected_set() -> None:
    assert set(jp_profiles.__all__) == set(_EXPECTED)


@pytest.mark.parametrize("name", sorted(_EXPECTED))
def test_constant_equals_spec_value(name: str) -> None:
    assert getattr(jp_profiles, name) == _EXPECTED[name]


def _python_sources() -> list[Path]:
    return [p for p in sorted(_SOURCE_ROOT.rglob("*.py")) if p.resolve() != _CONSTANTS_FILE]


@pytest.mark.parametrize("name", sorted(_EXPECTED))
def test_uri_literal_only_in_constants_module(name: str) -> None:
    uri = _EXPECTED[name]
    literals = (f'"{uri}"', f"'{uri}'")
    offenders = [
        str(p.relative_to(_REPO_ROOT))
        for p in _python_sources()
        if any(lit in p.read_text(encoding="utf-8") for lit in literals)
    ]
    assert not offenders, (
        f"{uri} is written as a literal outside {_CONSTANTS_FILE.name}; import {name} from "
        f"clinosim.modules.output.fhir_r4.lib.jp_profiles instead: {offenders}"
    )
