"""Positive / negative fixture tests for the US Core narrow-gate compliance axis.

CRITICAL: this test file is load-bearing. The axis exists to detect
silent must-support drift on the US Core AllPatients / Encounter /
Condition surfaces. Every check MUST have at least one negative fixture
that drives it below 100 % independently of the others — if a negative
fixture stops tripping (because someone widened the shape check to make
baseline "pass"), the axis has silently regressed.
"""

from __future__ import annotations

import pytest

from clinosim.eval.axes.us_core_compliance import (
    _check_condition_category_system,
    _check_encounter_class_v3_actcode,
    _check_patient_birthsex_extension,
    _check_patient_ethnicity_extension_shape,
    _check_patient_identifier,
    _check_patient_name_family_given,
    _check_patient_race_extension_shape,
)
from clinosim.eval.engine import Outcome

# --------------------------------------------------------------------------- #
# Canonical URLs and codes — DO NOT swap for a local alias; the axis's job
# is to check byte-identical URLs against the emit side.

_RACE_URL = "http://hl7.org/fhir/us/core/StructureDefinition/us-core-race"
_ETHNICITY_URL = "http://hl7.org/fhir/us/core/StructureDefinition/us-core-ethnicity"
_BIRTHSEX_URL = "http://hl7.org/fhir/us/core/StructureDefinition/us-core-birthsex"
_OMB_OID = "urn:oid:2.16.840.1.113883.6.238"
_V3_ACTCODE = "http://terminology.hl7.org/CodeSystem/v3-ActCode"
_CONDITION_CATEGORY = "http://terminology.hl7.org/CodeSystem/condition-category"


# --------------------------------------------------------------------------- #
# Patient identifier check


@pytest.mark.unit
class TestPatientIdentifier:
    def test_all_have_identifier_pass(self):
        patients = [{"identifier": [{"value": "P1"}]}, {"identifier": [{"value": "P2"}]}]
        result = _check_patient_identifier(patients)
        assert result.outcome is Outcome.PASS

    def test_missing_identifier_fail(self):
        patients = [{"identifier": [{"value": "P1"}]}, {}]
        result = _check_patient_identifier(patients)
        assert result.outcome is Outcome.FAIL
        assert result.detail["numerator"] == 1
        assert result.detail["denominator"] == 2

    def test_empty_cohort_na(self):
        result = _check_patient_identifier([])
        assert result.outcome is Outcome.NA


# --------------------------------------------------------------------------- #
# Patient name.family + name.given check


@pytest.mark.unit
class TestPatientNameFamilyGiven:
    def test_both_present_pass(self):
        patients = [{"name": [{"family": "Smith", "given": ["Jane"]}]}]
        assert _check_patient_name_family_given(patients).outcome is Outcome.PASS

    def test_family_only_fail(self):
        patients = [{"name": [{"family": "Smith"}]}]
        assert _check_patient_name_family_given(patients).outcome is Outcome.FAIL

    def test_given_only_fail(self):
        patients = [{"name": [{"given": ["Jane"]}]}]
        assert _check_patient_name_family_given(patients).outcome is Outcome.FAIL

    def test_multiple_names_one_complete_passes(self):
        patients = [{"name": [{"family": "Smith"}, {"given": ["Jane"]}]}]
        # `any()` semantics — different names in the list can jointly satisfy.
        assert _check_patient_name_family_given(patients).outcome is Outcome.PASS


# --------------------------------------------------------------------------- #
# Patient us-core-birthsex extension check


@pytest.mark.unit
class TestPatientBirthsexExtension:
    def test_valid_valuecode_pass(self):
        patients = [
            {"extension": [{"url": _BIRTHSEX_URL, "valueCode": "M"}]},
            {"extension": [{"url": _BIRTHSEX_URL, "valueCode": "F"}]},
        ]
        assert _check_patient_birthsex_extension(patients).outcome is Outcome.PASS

    def test_missing_extension_fail(self):
        patients = [{"extension": [{"url": _BIRTHSEX_URL, "valueCode": "M"}]}, {}]
        assert _check_patient_birthsex_extension(patients).outcome is Outcome.FAIL

    def test_invalid_valuecode_fail(self):
        patients = [{"extension": [{"url": _BIRTHSEX_URL, "valueCode": "X"}]}]
        # 'X' is not in the v3 AdministrativeGender valueset
        assert _check_patient_birthsex_extension(patients).outcome is Outcome.FAIL

    def test_all_valid_special_codes_pass(self):
        patients = [{"extension": [{"url": _BIRTHSEX_URL, "valueCode": v}]} for v in ("M", "F", "UNK", "OTH", "ASKU")]
        assert _check_patient_birthsex_extension(patients).outcome is Outcome.PASS


# --------------------------------------------------------------------------- #
# Patient us-core-race extension shape check


def _valid_race_ext() -> dict:
    return {
        "url": _RACE_URL,
        "extension": [
            {
                "url": "ombCategory",
                "valueCoding": {"system": _OMB_OID, "code": "2131-1", "display": "Other Race"},
            },
            {"url": "text", "valueString": "Other Race"},
        ],
    }


@pytest.mark.unit
class TestPatientRaceExtensionShape:
    def test_no_ext_na(self):
        patients = [{"extension": []}, {}]
        result = _check_patient_race_extension_shape(patients)
        # denominator = 0 → NA (distinguishes pre-migration from all-broken)
        assert result.outcome is Outcome.NA

    def test_valid_shape_pass(self):
        patients = [{"extension": [_valid_race_ext()]}]
        assert _check_patient_race_extension_shape(patients).outcome is Outcome.PASS

    def test_wrong_omb_oid_fail(self):
        bad = _valid_race_ext()
        bad["extension"][0]["valueCoding"]["system"] = "urn:oid:1.2.3.WRONG"
        patients = [{"extension": [bad]}]
        assert _check_patient_race_extension_shape(patients).outcome is Outcome.FAIL

    def test_missing_omb_category_fail(self):
        bad = _valid_race_ext()
        bad["extension"] = [s for s in bad["extension"] if s["url"] != "ombCategory"]
        patients = [{"extension": [bad]}]
        assert _check_patient_race_extension_shape(patients).outcome is Outcome.FAIL

    def test_missing_text_fail(self):
        bad = _valid_race_ext()
        bad["extension"] = [s for s in bad["extension"] if s["url"] != "text"]
        patients = [{"extension": [bad]}]
        assert _check_patient_race_extension_shape(patients).outcome is Outcome.FAIL


# --------------------------------------------------------------------------- #
# Patient us-core-ethnicity extension shape check (mirror of race)


def _valid_ethnicity_ext() -> dict:
    return {
        "url": _ETHNICITY_URL,
        "extension": [
            {
                "url": "ombCategory",
                "valueCoding": {
                    "system": _OMB_OID,
                    "code": "2135-2",
                    "display": "Hispanic or Latino",
                },
            },
            {"url": "text", "valueString": "Hispanic or Latino"},
        ],
    }


@pytest.mark.unit
class TestPatientEthnicityExtensionShape:
    def test_no_ext_na(self):
        result = _check_patient_ethnicity_extension_shape([{"extension": []}])
        assert result.outcome is Outcome.NA

    def test_valid_shape_pass(self):
        patients = [{"extension": [_valid_ethnicity_ext()]}]
        assert _check_patient_ethnicity_extension_shape(patients).outcome is Outcome.PASS

    def test_wrong_omb_oid_fail(self):
        bad = _valid_ethnicity_ext()
        bad["extension"][0]["valueCoding"]["system"] = "urn:oid:1.2.3.WRONG"
        patients = [{"extension": [bad]}]
        assert _check_patient_ethnicity_extension_shape(patients).outcome is Outcome.FAIL


# --------------------------------------------------------------------------- #
# Encounter.class check


@pytest.mark.unit
class TestEncounterClassV3ActCode:
    def test_all_v3_actcode_pass(self):
        encs = [
            {"class": {"system": _V3_ACTCODE, "code": "AMB"}},
            {"class": {"system": _V3_ACTCODE, "code": "IMP"}},
        ]
        assert _check_encounter_class_v3_actcode(encs).outcome is Outcome.PASS

    def test_wrong_class_system_fail(self):
        encs = [{"class": {"system": "http://example.com/wrong", "code": "AMB"}}]
        assert _check_encounter_class_v3_actcode(encs).outcome is Outcome.FAIL

    def test_missing_class_code_fail(self):
        encs = [{"class": {"system": _V3_ACTCODE}}]  # no `code`
        assert _check_encounter_class_v3_actcode(encs).outcome is Outcome.FAIL

    def test_missing_class_element_fail(self):
        encs = [{}]
        assert _check_encounter_class_v3_actcode(encs).outcome is Outcome.FAIL


# --------------------------------------------------------------------------- #
# Condition.category check


@pytest.mark.unit
class TestConditionCategorySystem:
    def test_correct_system_pass(self):
        conds = [{"category": [{"coding": [{"system": _CONDITION_CATEGORY, "code": "encounter-diagnosis"}]}]}]
        assert _check_condition_category_system(conds).outcome is Outcome.PASS

    def test_wrong_system_fail(self):
        conds = [{"category": [{"coding": [{"system": "http://example.com/wrong", "code": "x"}]}]}]
        assert _check_condition_category_system(conds).outcome is Outcome.FAIL

    def test_no_category_na(self):
        conds = [{}, {"category": [{}]}, {"category": [{"coding": []}]}]
        assert _check_condition_category_system(conds).outcome is Outcome.NA

    def test_mixed_correct_and_wrong_fail(self):
        conds = [
            {"category": [{"coding": [{"system": _CONDITION_CATEGORY, "code": "encounter-diagnosis"}]}]},
            {"category": [{"coding": [{"system": "http://wrong", "code": "x"}]}]},
        ]
        result = _check_condition_category_system(conds)
        assert result.outcome is Outcome.FAIL
        assert result.detail["numerator"] == 1
        assert result.detail["denominator"] == 2
