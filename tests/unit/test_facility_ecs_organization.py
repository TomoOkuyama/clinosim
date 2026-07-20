"""#313 session 61:JP-CLINS eReferral referralFrom/toSection.entry
Organization slice は discriminator (type: profile, path: resolve()) で
`JP_Organization_eCS` profile 準拠 Organization を要求。hospital-main は
JP Core profile のみで slice fail していた(v6.1 で 42 件 error)。

facility bundle に `hospital-main-ecs` 別 id を JP output 限定で emit し、
8 required fields 全て spec 準拠(fixedUri は spec 直接引用)。US output
には eCS profile 概念が無く emit しない。
"""

from __future__ import annotations

import pytest

from clinosim.modules.output.fhir_r4_adapter import _build_facility_bundle

pytestmark = pytest.mark.unit

_ECS_PROFILE_URL = "http://jpfhir.jp/fhir/eCS/StructureDefinition/JP_Organization_eCS"
_ECS_ID_SYSTEM = "http://jpfhir.jp/fhir/core/IdSystem/insurance-medical-institution-no"


def _hospital_config() -> dict:
    return {
        "available_departments": ["internal_medicine"],
        "wards": {"internal_medicine": ["4E"]},
        "resource_capacity": {"inpatient_beds": 50},
    }


def _find_org(bundle: dict, org_id: str) -> dict | None:
    for entry in bundle.get("entry", []):
        r = entry.get("resource", {})
        if r.get("resourceType") == "Organization" and r.get("id") == org_id:
            return r
    return None


def test_jp_emits_hospital_main_ecs_organization():
    """JP output に eCS 別 Organization `hospital-main-ecs` が存在。"""
    bundle = _build_facility_bundle(_hospital_config(), "JP")
    org = _find_org(bundle, "hospital-main-ecs")
    assert org is not None, "hospital-main-ecs must be emitted on JP output"


def test_us_does_not_emit_hospital_main_ecs():
    """US output は eCS Organization を emit しない(eReferral 自体が JP-only)。"""
    bundle = _build_facility_bundle(_hospital_config(), "US")
    org = _find_org(bundle, "hospital-main-ecs")
    assert org is None, "hospital-main-ecs must NOT be emitted on US output"


def test_ecs_organization_has_all_required_fields():
    """spec `StructureDefinition-JP-Organization-eCS.json` の 8 required
    fields 全て存在:meta.profile + meta.lastUpdated +
    identifier:medicalInstitutionCode(system fixedUri + value)+ type.coding
    + name + telecom.value + address.text + partOf.reference。"""
    bundle = _build_facility_bundle(_hospital_config(), "JP")
    org = _find_org(bundle, "hospital-main-ecs")
    assert org is not None

    # meta.profile + meta.lastUpdated
    assert _ECS_PROFILE_URL in org.get("meta", {}).get("profile", [])
    assert org.get("meta", {}).get("lastUpdated")

    # identifier:medicalInstitutionCode with fixedUri (spec 直接引用)
    idents = org.get("identifier", [])
    assert idents
    ident = idents[0]
    assert ident["system"] == _ECS_ID_SYSTEM
    assert ident["value"]  # non-empty

    # type.coding.system + code
    types = org.get("type", [])
    assert types and types[0]["coding"][0]["system"] and types[0]["coding"][0]["code"]

    # name
    assert org.get("name")

    # telecom.value + telecom.use (spec required binding, "home" 禁止)
    telecoms = org.get("telecom", [])
    assert telecoms and telecoms[0]["value"]
    assert telecoms[0].get("use") != "home"  # spec 禁止

    # address.text + address.use (spec required binding, "home" 禁止)
    addresses = org.get("address", [])
    assert addresses and addresses[0]["text"]
    assert addresses[0].get("use") != "home"

    # partOf.reference min=1 → hospital-main
    assert org.get("partOf", {}).get("reference") == "Organization/hospital-main"


def test_hospital_main_ecs_partof_hospital_main_still_emitted():
    """partOf ref 先の hospital-main は依然存在(reference integrity)。"""
    bundle = _build_facility_bundle(_hospital_config(), "JP")
    assert _find_org(bundle, "hospital-main") is not None
    assert _find_org(bundle, "hospital-main-ecs") is not None
