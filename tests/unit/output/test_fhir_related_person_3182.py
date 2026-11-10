"""Issue #3182: the emergency contact is a RelatedPerson, not Patient.contact.

``JP_Patient_eCheckupGeneral`` allows one ``Patient.contact`` and only for a
workplace contact, so the emergency contact (``v2-0131#C``) moves to a
``RelatedPerson`` that references the patient and carries the same data:
the emergency-contact role, the family relationship (``v3-RoleCode``), the
name and the phone. The structure is the same for every country; only the
declared profile (JP Core / US Core) and the label language differ.
"""

from __future__ import annotations

import pytest

from clinosim.locale.loader import load_marital_status
from clinosim.modules.output.fhir_r4.demographics.patient import _build_patient, patient_ref
from clinosim.modules.output.fhir_r4.demographics.related_person import (
    RELATED_PERSON_KEY_SYSTEM,
    _build_emergency_contact_related_person,
)

pytestmark = pytest.mark.unit

_V2_0131 = "http://terminology.hl7.org/CodeSystem/v2-0131"
_ROLE_CODE = "http://terminology.hl7.org/CodeSystem/v3-RoleCode"
_JP_RELATED_PERSON = "http://jpfhir.jp/fhir/core/StructureDefinition/JP_RelatedPerson"
_US_CORE_RELATED_PERSON = "http://hl7.org/fhir/us/core/StructureDefinition/us-core-relatedperson"


def _patient(rel: str = "spouse", **contact: str) -> dict:
    return {
        "patient_id": "POP-000042",
        "sex": "M",
        "date_of_birth": "1950-04-01",
        "name": {"family_name": "山田", "given_name": "太郎"},
        "contact": {
            "phone_home": "03-1234-5678",
            "phone_primary": "03-1234-5678",
            "emergency_contact_name": "山田 花子",
            "emergency_contact_phone": "090-1111-2222",
            "emergency_contact_relationship": rel,
            **contact,
        },
    }


def _codings(concept: dict) -> list[tuple[str, str, str]]:
    return [(c["system"], c["code"], c.get("display", "")) for c in concept["coding"]]


@pytest.mark.parametrize("country", ["JP", "US"])
def test_patient_carries_no_emergency_contact(country: str) -> None:
    patient = _build_patient(_patient(), country)
    assert "contact" not in patient
    # The patient's own phone stays on the Patient.
    assert patient["telecom"][0]["value"] == "03-1234-5678"


@pytest.mark.parametrize("country", ["JP", "US"])
def test_related_person_carries_the_emergency_contact(country: str) -> None:
    rp = _build_emergency_contact_related_person(_patient(), country)
    assert rp is not None
    assert rp["resourceType"] == "RelatedPerson"
    assert rp["active"] is True
    assert rp["patient"] == patient_ref("POP-000042")
    role, family = rp["relationship"]
    assert _codings(role) == [(_V2_0131, "C", "Emergency Contact")]
    assert _codings(family) == [(_ROLE_CODE, "SPS", "spouse")]
    assert rp["name"] == [{"text": "山田 花子"}]
    assert rp["telecom"] == [{"system": "phone", "value": "090-1111-2222", "use": "mobile"}]


def test_jp_labels_are_japanese_in_text() -> None:
    rp = _build_emergency_contact_related_person(_patient("MTH"), "JP")
    assert rp is not None
    role, family = rp["relationship"]
    assert role["text"] == "緊急連絡先"
    assert family["text"] == "母"
    assert _codings(family) == [(_ROLE_CODE, "MTH", "mother")]


def test_us_labels_add_no_duplicate_text() -> None:
    rp = _build_emergency_contact_related_person(_patient("child"), "US")
    assert rp is not None
    role, family = rp["relationship"]
    assert "text" not in family
    assert _codings(family) == [(_ROLE_CODE, "CHILD", "child")]
    assert role.get("text", "Emergency Contact") == "Emergency Contact"


def _sampled_relationships() -> list[str]:
    """Every relationship the locale tables can draw (Issue #3189)."""
    rels: set[str] = set()
    for country in ("US", "JP"):
        for by_band in load_marital_status(country)["emergency_contact"]["relationships"].values():
            for row in by_band.values():
                rels |= set(row)
    return sorted(rels)


@pytest.mark.parametrize("rel", _sampled_relationships())
def test_every_sampled_relationship_has_a_role_code(rel: str) -> None:
    for country in ("JP", "US"):
        rp = _build_emergency_contact_related_person(_patient(rel), country)
        assert rp is not None
        family = rp["relationship"][1]
        assert family["coding"][0]["system"] == _ROLE_CODE
        assert family["coding"][0]["display"]


def test_id_is_deterministic_and_keyed_on_the_patient() -> None:
    a = _build_emergency_contact_related_person(_patient(), "JP")
    b = _build_emergency_contact_related_person(_patient(), "US")
    other = _build_emergency_contact_related_person({**_patient(), "patient_id": "POP-000043"}, "JP")
    assert a is not None and b is not None and other is not None
    assert a["id"] == b["id"]
    assert a["id"].startswith("rp-") and len(a["id"]) == 15
    assert a["id"] != other["id"]
    assert {"system": RELATED_PERSON_KEY_SYSTEM, "value": "POP-000042-emergency-contact"} in a["identifier"]


def test_no_related_person_without_a_name_or_phone() -> None:
    p = _patient(emergency_contact_name="", emergency_contact_phone="")
    assert _build_emergency_contact_related_person(p, "JP") is None
    assert _build_emergency_contact_related_person({"patient_id": "POP-1"}, "US") is None


def test_unknown_relationship_keeps_only_the_emergency_contact_role() -> None:
    rp = _build_emergency_contact_related_person(_patient(""), "US")
    assert rp is not None
    assert [_codings(c) for c in rp["relationship"]] == [[(_V2_0131, "C", "Emergency Contact")]]


def test_bundle_builder_is_registered_after_the_patient() -> None:
    from clinosim.modules.output.fhir_r4 import available_builders

    names = available_builders()
    assert names.index("_bb_related_person") == names.index("_bb_patient") + 1


def test_country_profiles_are_declared() -> None:
    from clinosim.modules.output.fhir_r4.post_process import _apply_jp_core_profile, _apply_us_core_profile

    jp: dict = {"resourceType": "RelatedPerson"}
    _apply_jp_core_profile(jp)
    assert jp["meta"]["profile"] == [_JP_RELATED_PERSON]
    us: dict = {"resourceType": "RelatedPerson"}
    _apply_us_core_profile(us)
    assert us["meta"]["profile"] == [_US_CORE_RELATED_PERSON]
