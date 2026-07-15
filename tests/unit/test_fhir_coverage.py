"""Unit tests for JP Core Coverage FHIR output + privacy chokepoint (AD-54)."""

from __future__ import annotations

import json

import pytest

from clinosim.modules.output.fhir_r4_adapter import (
    _build_coverage_resources,
    _build_patient,
)

_NATIONAL_ID = "123456789018"

_PATIENT_JP = {
    "patient_id": "POP-000001",
    "sex": "M",
    "name": {"family_name": "山田", "given_name": "太郎"},
    "identity": {
        "national": {
            "country": "JP",
            "national_id": _NATIONAL_ID,
            "has_id_card": True,
            "id_card_linked_to_insurance": True,
        },
        "enrollments": [
            {
                "country": "JP",
                "category": "employee",
                "insurer_number": "01130012",
                "member_id": "12345678",
                "group_symbol": "1234",
                "branch_number": "01",
                "valid_from": None,
                "valid_to": None,
                "system_uri": "",
            }
        ],
        "card_acquired_on": None,
        "insurance_linked_on": None,
    },
}


@pytest.mark.unit
class TestCoverageBuilder:
    def test_emits_payer_org_and_coverage(self):
        res = _build_coverage_resources(_PATIENT_JP, "JP")
        kinds = [r["resourceType"] for r in res]
        assert kinds == ["Organization", "Coverage"]

    def test_coverage_core_fields(self):
        cov = next(r for r in _build_coverage_resources(_PATIENT_JP, "JP") if r["resourceType"] == "Coverage")
        assert cov["status"] == "active"
        assert cov["beneficiary"]["reference"] == "Patient/POP-000001"
        assert cov["payor"][0]["reference"] == "Organization/payer-01130012"
        assert cov["subscriberId"] == "1234:12345678"
        assert cov["dependent"] == "01"
        assert cov["identifier"][0]["value"] == "01130012:1234:12345678:01"
        assert cov["meta"]["profile"][0].endswith("JP_Coverage")

    def test_coverage_type_is_text_label(self):
        cov = next(r for r in _build_coverage_resources(_PATIENT_JP, "JP") if r["resourceType"] == "Coverage")
        # text-only CodeableConcept (no fabricated coding)
        assert "coding" not in cov["type"]
        assert cov["type"]["text"] == "被用者保険（被保険者）"

    def test_coverage_relationship_self_for_subscriber(self):
        cov = next(r for r in _build_coverage_resources(_PATIENT_JP, "JP") if r["resourceType"] == "Coverage")
        assert cov["relationship"]["coding"][0]["code"] == "self"

    def test_jp_core_extensions(self):
        cov = next(r for r in _build_coverage_resources(_PATIENT_JP, "JP") if r["resourceType"] == "Coverage")
        ext_by_url = {e["url"]: e["valueString"] for e in cov["extension"]}
        symbol_url = next(u for u in ext_by_url if u.endswith("InsuredPersonSymbol"))
        number_url = next(u for u in ext_by_url if u.endswith("InsuredPersonNumber"))
        sub_url = next(u for u in ext_by_url if u.endswith("InsuredPersonSubNumber"))
        assert ext_by_url[symbol_url] == "1234"
        assert ext_by_url[number_url] == "12345678"
        assert ext_by_url[sub_url] == "01"

    def test_payer_org_identifier_and_name(self):
        org = next(r for r in _build_coverage_resources(_PATIENT_JP, "JP") if r["resourceType"] == "Organization")
        assert org["id"] == "payer-01130012"
        assert org["identifier"][0]["value"] == "01130012"
        assert "jp-insurer-number-namingsystem" in org["identifier"][0]["system"]
        # name resolved to the real insurer name (not the number)
        assert org["name"] == "全国健康保険協会 東京支部"

    def test_payer_org_type_coding(self):
        org = next(r for r in _build_coverage_resources(_PATIENT_JP, "JP") if r["resourceType"] == "Organization")
        coding = org["type"][0]["coding"][0]
        assert coding["code"] == "pay"
        assert coding["system"].endswith("organization-type")

    def test_reference_integrity_payor_resolves(self):
        res = _build_coverage_resources(_PATIENT_JP, "JP")
        org_ids = {f"Organization/{r['id']}" for r in res if r["resourceType"] == "Organization"}
        cov = next(r for r in res if r["resourceType"] == "Coverage")
        assert cov["payor"][0]["reference"] in org_ids

    def test_no_enrollments_returns_empty(self):
        patient = {"patient_id": "P", "identity": {"enrollments": []}}
        assert _build_coverage_resources(patient, "JP") == []

    def test_us_has_no_coverage_config(self):
        # US has no identity.yaml fhir_coverage block in Phase 1 → no Coverage emitted.
        assert _build_coverage_resources(_PATIENT_JP, "US") == []


@pytest.mark.unit
class TestPrivacyChokepoint:
    def test_national_id_never_emitted(self):
        """national_id must not appear in any FHIR resource built from the patient."""
        coverage = _build_coverage_resources(_PATIENT_JP, "JP")
        patient = _build_patient(_PATIENT_JP, "JP")
        blob = json.dumps(coverage, ensure_ascii=False) + json.dumps(patient, ensure_ascii=False)
        assert _NATIONAL_ID not in blob
