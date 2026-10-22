"""Phase 3.α — Red SoT violation cleanup.

Four HL7 ValueSet display dicts (clinical / verification status for
Condition + AllergyIntolerance) and one LOINC blood-type fallback dict
previously duplicated the authority yamls under
``clinosim/codes/data/``. Phase 3.α retires the module-local maps and
routes every display lookup through ``clinosim.codes.lookup`` against
the authority yaml.

These tests lock the SoT contract so a reviewer who re-introduces a
module-local display map fails CI.
"""

from __future__ import annotations

import pytest

from clinosim.codes import lookup as code_lookup
from clinosim.modules.output.fhir_r4.post_process import populate

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# The four Red dicts are gone from the populate module namespace.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "symbol",
    [
        "_CONDITION_CLINICAL_DISPLAY",
        "_CONDITION_VER_STATUS_DISPLAY",
        "_ALLERGY_CLINICAL_DISPLAY",
        "_ALLERGY_VER_STATUS_DISPLAY",
    ],
)
def test_retired_display_dict_absent_from_populate_module(symbol: str):
    """A module-local dict whose entries duplicated an authority yaml
    is a Phase 3.α regression gate. Re-introducing one fails this test."""
    assert not hasattr(populate, symbol), (
        f"{symbol} should be retired (duplicated the matching hl7-*.yaml under clinosim/codes/data/)."
    )


# ---------------------------------------------------------------------------
# The authority yamls carry every code that the retired dicts used to.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "system_key, code, expected_en",
    [
        ("hl7-condition-clinical", "active", "Active"),
        ("hl7-condition-clinical", "recurrence", "Recurrence"),
        ("hl7-condition-clinical", "relapse", "Relapse"),
        ("hl7-condition-clinical", "inactive", "Inactive"),
        ("hl7-condition-clinical", "remission", "Remission"),
        ("hl7-condition-clinical", "resolved", "Resolved"),
        ("hl7-condition-ver-status", "unconfirmed", "Unconfirmed"),
        ("hl7-condition-ver-status", "provisional", "Provisional"),
        ("hl7-condition-ver-status", "differential", "Differential"),
        ("hl7-condition-ver-status", "confirmed", "Confirmed"),
        ("hl7-condition-ver-status", "refuted", "Refuted"),
        ("hl7-allergyintolerance-clinical", "active", "Active"),
        ("hl7-allergyintolerance-clinical", "inactive", "Inactive"),
        ("hl7-allergyintolerance-clinical", "resolved", "Resolved"),
        ("hl7-allergyintolerance-verification", "unconfirmed", "Unconfirmed"),
        ("hl7-allergyintolerance-verification", "presumed", "Presumed"),
        ("hl7-allergyintolerance-verification", "confirmed", "Confirmed"),
        ("hl7-allergyintolerance-verification", "refuted", "Refuted"),
    ],
)
def test_authority_yaml_has_display_for_every_retired_code(system_key: str, code: str, expected_en: str):
    """Every code that the retired dicts used to carry must resolve to
    its EN display via ``code_lookup``. A regression that drops a code
    from the authority yaml fails here before FHIR emit silently loses
    the display."""
    assert code_lookup(system_key, code, "en") == expected_en


# ---------------------------------------------------------------------------
# JA display emerges on JP output — a free side-effect of the migration.
# The pre-fix hardcoded dicts carried only EN; JP output on these status
# codings was silently English.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "system_key, code",
    [
        ("hl7-condition-clinical", "active"),
        ("hl7-condition-ver-status", "confirmed"),
        ("hl7-allergyintolerance-clinical", "resolved"),
        ("hl7-allergyintolerance-verification", "refuted"),
    ],
)
def test_authority_yaml_has_ja_display(system_key: str, code: str):
    """JA display MUST be non-empty for every code — the authority
    yamls carry both EN and JA, so JP output on these status codings
    no longer defaults to English."""
    ja = code_lookup(system_key, code, "ja")
    assert ja
    assert ja != code


# ---------------------------------------------------------------------------
# End-to-end: _populate_status_coding_display sets displays via the
# authority yaml for both EN and JA.
# ---------------------------------------------------------------------------


def test_populate_status_coding_display_resolves_en_from_authority():
    coding = {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/condition-clinical", "code": "active"}]}
    populate._populate_status_coding_display(coding, "hl7-condition-clinical", "en")
    assert coding["coding"][0]["display"] == "Active"


def test_populate_status_coding_display_resolves_ja_from_authority():
    coding = {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/condition-clinical", "code": "active"}]}
    populate._populate_status_coding_display(coding, "hl7-condition-clinical", "ja")
    assert coding["coding"][0]["display"] == "活動性"


def test_populate_status_coding_display_leaves_unknown_code_blank():
    """A code not in the authority yaml must not fabricate a display
    equal to the raw code string."""
    coding = {"coding": [{"system": "any", "code": "unknown-xyz"}]}
    populate._populate_status_coding_display(coding, "hl7-condition-clinical", "en")
    assert "display" not in coding["coding"][0]


# ---------------------------------------------------------------------------
# LOINC blood-type codes (883-9 / 10331-7) migrated into loinc.yaml.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "loinc_code, expected_en", [("883-9", "ABO group [Type] in Blood"), ("10331-7", "Rh [Type] in Blood")]
)
def test_blood_type_loinc_codes_resolve_via_authority(loinc_code: str, expected_en: str):
    """The ABO + Rh LOINC codes previously lived in a module-local
    fallback dict inside ``fhir_r4/labs/blood_type.py``. Phase 3.α
    moved them into ``clinosim/codes/data/loinc.yaml`` so a single
    authority lookup is enough."""
    assert code_lookup("loinc", loinc_code, "en") == expected_en


def test_blood_type_module_local_fallback_dict_absent():
    """The ``_LOINC_DISPLAY_EN_BY_CODE`` fallback dict is retired."""
    from clinosim.modules.output.fhir_r4.labs import blood_type

    assert not hasattr(blood_type, "_LOINC_DISPLAY_EN_BY_CODE")
    assert not hasattr(blood_type, "_LOINC_ABO_GROUP_DISPLAY_EN")
    assert not hasattr(blood_type, "_LOINC_RH_GROUP_DISPLAY_EN")
