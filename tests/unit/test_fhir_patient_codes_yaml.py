"""_fhir_patient.py's marital status / language displays must resolve via
codes/data/*.yaml + code_lookup (AD-30 sibling: "never hardcode clinical
display dicts in Python"), not the hardcoded _MARITAL_DISPLAY(_JA) /
_LANG_DISPLAY dicts (2026-07-02 grand design review, display-dict migration).
"""

import pytest

from clinosim.codes import get_system_uri, lookup
from clinosim.modules.output.fhir_r4.demographics.patient import _build_patient

pytestmark = pytest.mark.unit


def test_marital_status_display_us(patient_dict_factory):
    resource = _build_patient(patient_dict_factory(marital="M"), "US")
    coding = resource["maritalStatus"]["coding"][0]
    assert coding["display"] == "Married"
    assert coding["system"] == get_system_uri("hl7-v3-maritalstatus")


def test_marital_status_display_jp(patient_dict_factory):
    resource = _build_patient(patient_dict_factory(marital="M"), "JP")
    coding = resource["maritalStatus"]["coding"][0]
    assert coding["display"] == "既婚"


@pytest.mark.parametrize(
    "code,en",
    [
        ("S", "Never Married"),
        ("D", "Divorced"),
        ("W", "Widowed"),
        ("U", "Unmarried"),
        ("T", "Domestic partner"),
    ],
)
def test_all_marital_codes_resolve_us(patient_dict_factory, code, en):
    resource = _build_patient(patient_dict_factory(marital=code), "US")
    assert resource["maritalStatus"]["coding"][0]["display"] == en


def test_language_display_us(patient_dict_factory):
    # Issue #1764: US output must use the BCP-47 canonical display
    # (`English (United States)`, with a space before the paren) — the
    # US Core v9 / HL7 FHIR validator's BCP-47 binding rejects the
    # fhir-jp-validator form `English(US)` as a display mismatch.
    resource = _build_patient(patient_dict_factory(lang="en-US"), "US")
    coding = resource["communication"][0]["language"]["coding"][0]
    assert coding["display"] == "English (United States)"


def test_language_display_jp(patient_dict_factory):
    # JP output continues to emit the fhir-jp-validator-registered form
    # (no space before paren) — session 58 Chain #7 resolved 580 v4 errors
    # against the jp-validator tx-server by shifting to this spelling.
    resource = _build_patient(patient_dict_factory(lang="ja-JP"), "JP")
    coding = resource["communication"][0]["language"]["coding"][0]
    assert coding["display"] == "Japanese(Japan)"


def test_language_display_jp_en_us(patient_dict_factory):
    # Mixed case: a JP-locale patient whose preferred_language is en-US
    # should still receive the jp-validator form on JP output.
    resource = _build_patient(patient_dict_factory(lang="en-US"), "JP")
    coding = resource["communication"][0]["language"]["coding"][0]
    assert coding["display"] == "English(US)"


def test_marital_status_yaml_matches_direct_lookup():
    assert lookup("hl7-v3-maritalstatus", "M", "en") == "Married"
    assert lookup("hl7-v3-maritalstatus", "M", "ja") == "既婚"


def test_language_yaml_matches_direct_lookup():
    # `en` field keeps the jp-validator form (JP output path).
    assert lookup("bcp-47-language", "en-US", "en") == "English(US)"
    assert lookup("bcp-47-language", "ja-JP", "en") == "Japanese(Japan)"
    # `en_canonical` holds the BCP-47 canonical form (US output path).
    assert lookup("bcp-47-language", "en-US", "en_canonical") == "English (United States)"
    assert lookup("bcp-47-language", "ja-JP", "en_canonical") == "Japanese (Japan)"
