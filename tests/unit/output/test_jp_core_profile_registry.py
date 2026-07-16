"""Pin tests for `_JP_CORE_PROFILES` registry(session 53 issue #145 追加分)。

JP Core StructureDefinition URL は iris4h-ai/jp_core/package/
StructureDefinition-jp-*.json の `.url` fixedUri を直接引用する
(session 51 rule)。本 test は registry の URL が spec と一致することと、
session 53 で追加した 4 resource type(ServiceRequest / DocumentReference /
FamilyMemberHistory / ImagingStudy)が確かに含まれていることを pin する。
"""

from __future__ import annotations

import pytest


@pytest.mark.parametrize(
    "resource_type,expected_url",
    [
        ("ServiceRequest", "http://jpfhir.jp/fhir/core/StructureDefinition/JP_ServiceRequest_Common"),
        ("DocumentReference", "http://jpfhir.jp/fhir/core/StructureDefinition/JP_DocumentReference"),
        ("FamilyMemberHistory", "http://jpfhir.jp/fhir/core/StructureDefinition/JP_FamilyMemberHistory"),
        ("ImagingStudy", "http://jpfhir.jp/fhir/core/StructureDefinition/JP_ImagingStudy_Radiology"),
    ],
)
def test_jp_core_profile_registered_for_resource(resource_type: str, expected_url: str) -> None:
    """Session 53 (#145): 4 追加 resource type に JP Core profile が登録されている。"""
    from clinosim.modules.output.fhir_r4_adapter import _JP_CORE_PROFILES

    profiles = _JP_CORE_PROFILES.get(resource_type)
    assert profiles is not None, f"{resource_type} missing from _JP_CORE_PROFILES registry"
    assert expected_url in profiles, f"{resource_type} profiles={profiles} does not include {expected_url}"


def test_jp_core_profile_registry_no_regression() -> None:
    """既存 14 resource type + 追加 4 = 18 resource type が全て存在。"""
    from clinosim.modules.output.fhir_r4_adapter import _JP_CORE_PROFILES

    expected = {
        "Patient",
        "Encounter",
        "Condition",
        "Coverage",
        "Observation",
        "MedicationRequest",
        "MedicationAdministration",
        "AllergyIntolerance",
        "Immunization",
        "Practitioner",
        "PractitionerRole",
        "Organization",
        "DiagnosticReport",
        "Procedure",
        # session 53 additions
        "ServiceRequest",
        "DocumentReference",
        "FamilyMemberHistory",
        "ImagingStudy",
    }
    missing = expected - set(_JP_CORE_PROFILES.keys())
    assert not missing, f"registry lost resource types: {missing}"


def test_apply_jp_core_profile_attaches_new_profiles() -> None:
    """`_apply_jp_core_profile` が新 4 resource type にも profile を付与する。"""
    from clinosim.modules.output.fhir_r4_adapter import _apply_jp_core_profile

    for rt, expected_url in [
        ("ServiceRequest", "http://jpfhir.jp/fhir/core/StructureDefinition/JP_ServiceRequest_Common"),
        ("DocumentReference", "http://jpfhir.jp/fhir/core/StructureDefinition/JP_DocumentReference"),
        ("FamilyMemberHistory", "http://jpfhir.jp/fhir/core/StructureDefinition/JP_FamilyMemberHistory"),
        ("ImagingStudy", "http://jpfhir.jp/fhir/core/StructureDefinition/JP_ImagingStudy_Radiology"),
    ]:
        resource: dict = {"resourceType": rt}
        _apply_jp_core_profile(resource)
        assert expected_url in resource["meta"]["profile"], f"{rt}: profile not attached"


def test_apply_jp_core_profile_is_idempotent() -> None:
    """既に profile がある resource には再追加しない。"""
    from clinosim.modules.output.fhir_r4_adapter import _apply_jp_core_profile

    url = "http://jpfhir.jp/fhir/core/StructureDefinition/JP_ServiceRequest_Common"
    resource: dict = {"resourceType": "ServiceRequest", "meta": {"profile": [url]}}
    _apply_jp_core_profile(resource)
    assert resource["meta"]["profile"].count(url) == 1


def test_jp_core_profile_not_applied_to_resource_without_registry() -> None:
    """JP Core が profile を publish していない CareTeam / Composition /
    ClinicalImpression / Endpoint には _JP_CORE_PROFILES 経由の profile は
    付与されない(Composition は builder 側で JP-CLINS profile を別途 attach)。"""
    from clinosim.modules.output.fhir_r4_adapter import _apply_jp_core_profile

    for rt in ("CareTeam", "Composition", "ClinicalImpression", "Endpoint"):
        resource: dict = {"resourceType": rt}
        _apply_jp_core_profile(resource)
        # meta 未初期化 or profile 空
        assert not resource.get("meta", {}).get("profile"), (
            f"{rt} unexpectedly received JP Core profile via registry: {resource.get('meta')}"
        )
