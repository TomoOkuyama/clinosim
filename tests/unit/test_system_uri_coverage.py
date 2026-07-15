"""Unit tests for FHIR system-URI centralization (URI-1).

All FHIR code-system URIs emitted by the adapter must resolve through
clinosim.codes.get_system_uri() rather than being hardcoded as string literals,
so the canonical URI for a code system is defined in exactly one place.

These tests pin the exact URI for each key (byte-identity guard = golden-safe)
and assert the adapter no longer hardcodes any of those code-system URIs.
"""

import re
from pathlib import Path

import pytest

from clinosim.codes import get_system_uri

# key -> canonical URI. Adding/renaming a key must keep the URI byte-identical
# to what the adapter previously emitted (golden output is unchanged).
EXPECTED_URIS = {
    "hl7-condition-clinical": "http://terminology.hl7.org/CodeSystem/condition-clinical",
    "hl7-condition-ver-status": "http://terminology.hl7.org/CodeSystem/condition-ver-status",
    "hl7-condition-category": "http://terminology.hl7.org/CodeSystem/condition-category",
    "hl7-location-physical-type": "http://terminology.hl7.org/CodeSystem/location-physical-type",
    "hl7-referencerange-meaning": "http://terminology.hl7.org/CodeSystem/referencerange-meaning",
    "hl7-organization-type": "http://terminology.hl7.org/CodeSystem/organization-type",
    "hl7-v3-rolecode": "http://terminology.hl7.org/CodeSystem/v3-RoleCode",
    "hl7-v3-participationtype": "http://terminology.hl7.org/CodeSystem/v3-ParticipationType",
    "hl7-v3-administrativegender": "http://terminology.hl7.org/CodeSystem/v3-AdministrativeGender",
    "hl7-v3-actpriority": "http://terminology.hl7.org/CodeSystem/v3-ActPriority",
    "hl7-v2-0360": "http://terminology.hl7.org/CodeSystem/v2-0360",
    "hl7-v2-0203": "http://terminology.hl7.org/CodeSystem/v2-0203",
    "hl7-v2-0131": "http://terminology.hl7.org/CodeSystem/v2-0131",
    "hl7-v2-0092": "http://terminology.hl7.org/CodeSystem/v2-0092",
    "hl7-service-type": "http://terminology.hl7.org/CodeSystem/service-type",
    "hl7-practitioner-role": "http://terminology.hl7.org/CodeSystem/practitioner-role",
    "hl7-discharge-disposition": "http://terminology.hl7.org/CodeSystem/discharge-disposition",
    "hl7-diagnosis-role": "http://terminology.hl7.org/CodeSystem/diagnosis-role",
    "hl7-allergyintolerance-verification": "http://terminology.hl7.org/CodeSystem/allergyintolerance-verification",
    "hl7-allergyintolerance-clinical": "http://terminology.hl7.org/CodeSystem/allergyintolerance-clinical",
    "hl7-admit-source": "http://terminology.hl7.org/CodeSystem/admit-source",
    "us-core-documentreference-category": "http://hl7.org/fhir/us/core/CodeSystem/us-core-documentreference-category",
    "occupation-category": "http://clinosim.example.org/CodeSystem/occupation-category",
}

_ADAPTER = Path(__file__).resolve().parent.parent.parent / "clinosim" / "modules" / "output" / "fhir_r4_adapter.py"


@pytest.mark.unit
class TestSystemUriCoverage:
    @pytest.mark.parametrize("key,uri", sorted(EXPECTED_URIS.items()))
    def test_get_system_uri_returns_canonical(self, key, uri):
        assert get_system_uri(key) == uri

    def test_adapter_does_not_hardcode_code_system_uris(self):
        src = _ADAPTER.read_text(encoding="utf-8")
        # A `"system": "http://..."` literal means a code-system URI escaped
        # centralization. Extension/profile canonical URLs use `"url":` and are
        # intentionally out of scope (not code systems).
        offenders = re.findall(r'"system":\s*"https?://[^"]+"', src)
        assert offenders == [], f"hardcoded code-system URIs remain: {offenders}"
