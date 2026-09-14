"""Positive / negative fixture tests for the JP Core narrow-gate compliance axis.

CRITICAL: this test file is load-bearing. The axis exists to detect
silent must-support drift on the JP Core Patient / Encounter /
MedicationRequest surfaces. Every check MUST have at least one
negative fixture that drives it below 100 % independently of the
others — if a negative fixture stops tripping (because someone
widened the shape check to make baseline "pass"), the axis has
silently regressed.
"""

from __future__ import annotations

import pytest

from clinosim.eval.axes.jp_core_compliance import (
    _check_encounter_class_present,
    _check_encounter_period_present,
    _check_medicationrequest_medication_coding,
    _check_patient_identifier,
    _check_patient_kanji_representation,
    _check_patient_name_family_given,
    _check_patient_profile_declared,
)
from clinosim.eval.engine import Outcome

_JP_PATIENT_PROFILE = "http://jpfhir.jp/fhir/core/StructureDefinition/JP_Patient"
_JP_PATIENT_ECS_PROFILE = "http://jpfhir.jp/fhir/eCS/StructureDefinition/JP_Patient_eCS"
_ISO_21090_EN_REPRESENTATION = "http://hl7.org/fhir/StructureDefinition/iso21090-EN-representation"


# --------------------------------------------------------------------------- #
# Patient profile check


@pytest.mark.unit
class TestPatientProfileDeclared:
    def test_jp_core_pass(self):
        patients = [{"meta": {"profile": [_JP_PATIENT_PROFILE]}}]
        assert _check_patient_profile_declared(patients).outcome is Outcome.PASS

    def test_ecs_only_fails(self):
        # JP-CLINS eCS Patient (jpfhir.jp/fhir/eCS/…) is a JP-CLINS
        # declaration, not a JP Core declaration. Issue #1418 spec
        # requires BOTH JP Core AND JP-CLINS for JP output; eCS alone
        # does not satisfy the JP Core prefix and correctly fails.
        patients = [{"meta": {"profile": [_JP_PATIENT_ECS_PROFILE]}}]
        assert _check_patient_profile_declared(patients).outcome is Outcome.FAIL

    def test_both_jp_core_and_ecs_passes(self):
        # Real production JP Patient emits BOTH profiles side-by-side.
        # The JP Core one satisfies this check independently of the eCS one.
        patients = [{"meta": {"profile": [_JP_PATIENT_PROFILE, _JP_PATIENT_ECS_PROFILE]}}]
        assert _check_patient_profile_declared(patients).outcome is Outcome.PASS

    def test_missing_profile_fail(self):
        patients = [{"meta": {"profile": [_JP_PATIENT_PROFILE]}}, {}]
        assert _check_patient_profile_declared(patients).outcome is Outcome.FAIL

    def test_unrelated_profile_fail(self):
        patients = [{"meta": {"profile": ["http://hl7.org/fhir/StructureDefinition/Patient"]}}]
        assert _check_patient_profile_declared(patients).outcome is Outcome.FAIL


# --------------------------------------------------------------------------- #
# Patient identifier check


@pytest.mark.unit
class TestPatientIdentifier:
    def test_pass(self):
        patients = [{"identifier": [{"value": "1"}]}, {"identifier": [{"value": "2"}]}]
        assert _check_patient_identifier(patients).outcome is Outcome.PASS

    def test_fail(self):
        patients = [{"identifier": [{"value": "1"}]}, {}]
        assert _check_patient_identifier(patients).outcome is Outcome.FAIL


# --------------------------------------------------------------------------- #
# Patient name.family + name.given check


@pytest.mark.unit
class TestPatientNameFamilyGiven:
    def test_pass(self):
        patients = [{"name": [{"family": "山田", "given": ["太郎"]}]}]
        assert _check_patient_name_family_given(patients).outcome is Outcome.PASS

    def test_family_only_fail(self):
        patients = [{"name": [{"family": "山田"}]}]
        assert _check_patient_name_family_given(patients).outcome is Outcome.FAIL

    def test_given_only_fail(self):
        patients = [{"name": [{"given": ["太郎"]}]}]
        assert _check_patient_name_family_given(patients).outcome is Outcome.FAIL


# --------------------------------------------------------------------------- #
# Patient kanji (IDE) representation check


def _ide_name() -> dict:
    return {
        "family": "山田",
        "given": ["太郎"],
        "extension": [{"url": _ISO_21090_EN_REPRESENTATION, "valueCode": "IDE"}],
    }


def _syl_name() -> dict:
    return {
        "family": "ヤマダ",
        "given": ["タロウ"],
        "extension": [{"url": _ISO_21090_EN_REPRESENTATION, "valueCode": "SYL"}],
    }


@pytest.mark.unit
class TestPatientKanjiRepresentation:
    def test_ide_present_pass(self):
        patients = [{"name": [_ide_name()]}]
        assert _check_patient_kanji_representation(patients).outcome is Outcome.PASS

    def test_syl_only_fail(self):
        # Kana-only patient — no IDE variant. Fails this axis (locale axis
        # tracks kana presence separately as a WARN, not gated here).
        patients = [{"name": [_syl_name()]}]
        assert _check_patient_kanji_representation(patients).outcome is Outcome.FAIL

    def test_multiple_names_ide_present_pass(self):
        patients = [{"name": [_syl_name(), _ide_name()]}]
        assert _check_patient_kanji_representation(patients).outcome is Outcome.PASS

    def test_no_extension_fail(self):
        patients = [{"name": [{"family": "山田", "given": ["太郎"]}]}]  # no ext
        assert _check_patient_kanji_representation(patients).outcome is Outcome.FAIL


# --------------------------------------------------------------------------- #
# Encounter checks


@pytest.mark.unit
class TestEncounterClassPresent:
    def test_pass(self):
        encs = [{"class": {"code": "AMB"}}, {"class": {"code": "IMP"}}]
        assert _check_encounter_class_present(encs).outcome is Outcome.PASS

    def test_missing_code_fail(self):
        encs = [{"class": {"system": "http://x", "code": "AMB"}}, {"class": {}}]
        assert _check_encounter_class_present(encs).outcome is Outcome.FAIL

    def test_missing_class_fail(self):
        encs = [{}]
        assert _check_encounter_class_present(encs).outcome is Outcome.FAIL


@pytest.mark.unit
class TestEncounterPeriodPresent:
    def test_pass(self):
        encs = [{"period": {"start": "2026-01-01T09:00:00+09:00"}}]
        assert _check_encounter_period_present(encs).outcome is Outcome.PASS

    def test_missing_start_fail(self):
        encs = [{"period": {"end": "2026-01-02"}}]  # end without start
        assert _check_encounter_period_present(encs).outcome is Outcome.FAIL

    def test_missing_period_fail(self):
        encs = [{}]
        assert _check_encounter_period_present(encs).outcome is Outcome.FAIL


# --------------------------------------------------------------------------- #
# MedicationRequest check


@pytest.mark.unit
class TestMedicationRequestCoding:
    def test_pass(self):
        mrs = [{"medicationCodeableConcept": {"coding": [{"system": "http://x", "code": "123"}]}}]
        assert _check_medicationrequest_medication_coding(mrs).outcome is Outcome.PASS

    def test_missing_coding_fail(self):
        mrs = [{"medicationCodeableConcept": {"text": "ドラッグ"}}]  # no coding
        assert _check_medicationrequest_medication_coding(mrs).outcome is Outcome.FAIL

    def test_no_cc_at_all_na(self):
        # If MR uses medicationReference exclusively (currently unused by
        # clinosim), the check is out-of-scope → NA.
        mrs = [{"medicationReference": {"reference": "Medication/1"}}]
        assert _check_medicationrequest_medication_coding(mrs).outcome is Outcome.NA

    def test_mixed_correct_and_wrong_fail(self):
        mrs = [
            {"medicationCodeableConcept": {"coding": [{"code": "x"}]}},
            {"medicationCodeableConcept": {"text": "y"}},
        ]
        result = _check_medicationrequest_medication_coding(mrs)
        assert result.outcome is Outcome.FAIL
        assert result.detail["numerator"] == 1
        assert result.detail["denominator"] == 2
