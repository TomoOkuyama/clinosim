"""_fhir_patient.py's marital status / language displays must resolve via
codes/data/*.yaml + code_lookup (AD-30 sibling: "never hardcode clinical
display dicts in Python"), not the hardcoded _MARITAL_DISPLAY(_JA) /
_LANG_DISPLAY dicts (2026-07-02 grand design review, display-dict migration).
"""

import pytest

from clinosim.codes import get_system_uri, lookup
from clinosim.modules.output._fhir_patient import _build_patient

pytestmark = pytest.mark.unit


def _patient(marital: str = "", lang: str = "") -> dict:
    p = {"patient_id": "P1", "name": {"family_name": "Smith", "given_name": "Jane"}, "sex": "F"}
    if marital:
        p["marital_status"] = marital
    if lang:
        p["preferred_language"] = lang
    return p


def test_marital_status_display_us():
    resource = _build_patient(_patient(marital="M"), "US")
    coding = resource["maritalStatus"]["coding"][0]
    assert coding["display"] == "Married"
    assert coding["system"] == get_system_uri("hl7-v3-maritalstatus")


def test_marital_status_display_jp():
    resource = _build_patient(_patient(marital="M"), "JP")
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
def test_all_marital_codes_resolve_us(code, en):
    resource = _build_patient(_patient(marital=code), "US")
    assert resource["maritalStatus"]["coding"][0]["display"] == en


def test_language_display():
    # Session 58 Chain #7: Patient.communication.language always emits the
    # English display (BCP-47 is English-only per the validator's terminology).
    resource = _build_patient(_patient(lang="en-US"), "US")
    coding = resource["communication"][0]["language"]["coding"][0]
    assert coding["display"] == "English(US)"


def test_language_display_ja():
    # Even for JP output, the emitted display is the English form the tx-server
    # accepts (session 58 Chain #7 — 580 v4 errors resolved by this shift).
    resource = _build_patient(_patient(lang="ja-JP"), "JP")
    coding = resource["communication"][0]["language"]["coding"][0]
    assert coding["display"] == "Japanese(Japan)"


def test_marital_status_yaml_matches_direct_lookup():
    assert lookup("hl7-v3-maritalstatus", "M", "en") == "Married"
    assert lookup("hl7-v3-maritalstatus", "M", "ja") == "既婚"


def test_language_yaml_matches_direct_lookup():
    assert lookup("bcp-47-language", "en-US", "en") == "English(US)"
    assert lookup("bcp-47-language", "ja-JP", "en") == "Japanese(Japan)"
