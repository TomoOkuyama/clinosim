"""JP-CLINS eReferral / eDischargeSummary Composition slice discriminators
(type: profile, path: resolve()) require a `JP_Organization_eCS`-profile
Organization at referralFrom/toOrganization + author + custodian.

Issue #746 (unify): the `hospital-main` Organization now declares BOTH
`JP_Organization` and `JP_Organization_eCS` inline on JP output, with the
eCS profile's must-support fields populated. The pre-#746 workaround —
emitting a second Organization `hospital-main-ecs` purely to carry the
eCS profile — is retired. Consumers of the eReferral / eDischargeSummary
references (`documents/composition.py`) now resolve to the same unified
`hospital-main` resource, and the slice discriminator's `resolve()` finds
the eCS profile on that resource.

Assertions here pin the merged shape so a regression that either drops
the eCS profile URI, drops a must-support field, or reintroduces the
separate `hospital-main-ecs` id would fail immediately.
"""

from __future__ import annotations

import pytest

from clinosim.modules.output.fhir_r4.encounters.facility import _build_facility_bundle

pytestmark = pytest.mark.unit

_BASE_PROFILE_URL = "http://jpfhir.jp/fhir/core/StructureDefinition/JP_Organization"
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


def test_jp_hospital_main_declares_both_base_and_ecs_profiles():
    """Unified emit: hospital-main carries both JP_Organization and JP_Organization_eCS on JP output."""
    bundle = _build_facility_bundle(_hospital_config(), "JP")
    org = _find_org(bundle, "hospital-main")
    assert org is not None, "hospital-main must be emitted on JP output"
    profiles = org.get("meta", {}).get("profile", [])
    assert _BASE_PROFILE_URL in profiles, "JP_Organization (base) profile must remain declared"
    assert _ECS_PROFILE_URL in profiles, "JP_Organization_eCS profile must now be declared alongside base"


def test_jp_no_longer_emits_separate_hospital_main_ecs_organization():
    """Issue #746: the workaround duplicate `hospital-main-ecs` is retired."""
    bundle = _build_facility_bundle(_hospital_config(), "JP")
    assert _find_org(bundle, "hospital-main-ecs") is None, (
        "hospital-main-ecs must not be emitted — its eCS role is now merged into hospital-main"
    )


def test_us_hospital_main_has_no_jp_profiles():
    """US output does not declare JP-CLINS profile URIs on Organization (unchanged behaviour)."""
    bundle = _build_facility_bundle(_hospital_config(), "US")
    org = _find_org(bundle, "hospital-main")
    assert org is not None
    profiles = org.get("meta", {}).get("profile", [])
    assert _BASE_PROFILE_URL not in profiles
    assert _ECS_PROFILE_URL not in profiles


def test_jp_hospital_main_carries_all_ecs_must_support_fields():
    """spec `StructureDefinition-JP-Organization-eCS.json` must-support fields.

    Verifies the eCS-required set as populated on the unified hospital-main
    (min=1 elements per the SD's differential): meta.profile +
    meta.lastUpdated + identifier:medicalInstitutionCode.system fixedUri +
    identifier value + type.coding + name + telecom.value + address.text.
    partOf is spec-optional (min=0 base) and skipped because hospital-main
    is the root org with no parent.
    """
    bundle = _build_facility_bundle(_hospital_config(), "JP")
    org = _find_org(bundle, "hospital-main")
    assert org is not None

    # meta.profile (contains eCS) + meta.lastUpdated
    assert _ECS_PROFILE_URL in org.get("meta", {}).get("profile", [])
    assert org.get("meta", {}).get("lastUpdated"), "meta.lastUpdated required by JP_Organization_eCS"

    # identifier:medicalInstitutionCode with fixedUri (spec 直接引用)
    idents = org.get("identifier", [])
    assert idents, "identifier[] required — JP_Organization_eCS.identifier min=1"
    codes = [i for i in idents if i.get("system") == _ECS_ID_SYSTEM]
    assert codes, "identifier:medicalInstitutionCode.system fixedUri must be present"
    assert codes[0]["value"], "identifier:medicalInstitutionCode.value must be non-empty"

    # type.coding.system + code (unchanged: prov)
    types = org.get("type", [])
    assert types and types[0]["coding"][0]["system"] and types[0]["coding"][0]["code"]

    # name (min=1)
    assert org.get("name"), "Organization.name required"

    # telecom.value + telecom.use (spec required binding: "home" 禁止)
    telecoms = org.get("telecom", [])
    assert telecoms and telecoms[0]["value"], "telecom.value required by eCS"
    assert telecoms[0].get("use") != "home", "eCS telecom.use required binding forbids 'home'"

    # address.text + address.use (spec required binding: "home" 禁止)
    addresses = org.get("address", [])
    assert addresses and addresses[0]["text"], "address.text required by eCS"
    assert addresses[0].get("use") != "home", "eCS address.use required binding forbids 'home'"


def test_jp_organization_count_is_deduplicated():
    """The two-Organization workaround inflated the emitted Organization count by
    one on JP output. Post-unify, there must be exactly one hospital-main.
    """
    bundle = _build_facility_bundle(_hospital_config(), "JP")
    ids = [
        e["resource"]["id"]
        for e in bundle.get("entry", [])
        if e.get("resource", {}).get("resourceType") == "Organization"
        and e["resource"].get("id", "").startswith("hospital-main")
    ]
    assert ids == ["hospital-main"], f"expected exactly one hospital-main Organization, got {ids}"
