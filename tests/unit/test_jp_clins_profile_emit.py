"""Unit tests for JP-CLINS eCS profile URL emission (P2-13 PR1).

JP-CLINS v1.12.0 canonical URLs verified 2026-07-12 against
https://jpfhir.jp/fhir/clins/igv1/artifacts.html — path is /fhir/eCS/,
5 profiles cover the 6-information-item domain (傷病名 + 感染症 share
JP_Condition_eCS; DiagnosticReport is NOT in JP-CLINS scope).
"""

from __future__ import annotations

import pytest

from clinosim.modules.output.fhir_r4_adapter import (
    _JP_CLINS_PROFILES,
    _apply_jp_clins_profile,
    _is_lab_observation,
)


@pytest.mark.unit
class TestApplyJpClinsProfile:
    def test_allergy_gets_ecs_profile(self):
        r = {"resourceType": "AllergyIntolerance"}
        _apply_jp_clins_profile(r)
        assert r["meta"]["profile"] == [
            "http://jpfhir.jp/fhir/eCS/StructureDefinition/JP_AllergyIntolerance_eCS"
        ]

    def test_medication_request_gets_ecs_profile(self):
        r = {"resourceType": "MedicationRequest"}
        _apply_jp_clins_profile(r)
        assert (
            "http://jpfhir.jp/fhir/eCS/StructureDefinition/JP_MedicationRequest_eCS"
            in r["meta"]["profile"]
        )

    def test_procedure_gets_ecs_profile(self):
        r = {"resourceType": "Procedure"}
        _apply_jp_clins_profile(r)
        assert (
            "http://jpfhir.jp/fhir/eCS/StructureDefinition/JP_Procedure_eCS"
            in r["meta"]["profile"]
        )

    def test_condition_gets_ecs_profile(self):
        r = {"resourceType": "Condition"}
        _apply_jp_clins_profile(r)
        assert (
            "http://jpfhir.jp/fhir/eCS/StructureDefinition/JP_Condition_eCS"
            in r["meta"]["profile"]
        )

    def test_idempotent_no_duplicate(self):
        r = {"resourceType": "AllergyIntolerance"}
        _apply_jp_clins_profile(r)
        _apply_jp_clins_profile(r)
        _apply_jp_clins_profile(r)
        profs = r["meta"]["profile"]
        assert len(profs) == 1

    def test_unregistered_resource_type_noop(self):
        r = {"resourceType": "Encounter"}
        _apply_jp_clins_profile(r)
        assert "meta" not in r or not r.get("meta", {}).get("profile")

    def test_preserves_existing_jp_core_profile(self):
        r = {
            "resourceType": "MedicationRequest",
            "meta": {"profile": [
                "http://jpfhir.jp/fhir/core/StructureDefinition/JP_MedicationRequest"
            ]},
        }
        _apply_jp_clins_profile(r)
        assert (
            "http://jpfhir.jp/fhir/core/StructureDefinition/JP_MedicationRequest"
            in r["meta"]["profile"]
        )
        assert (
            "http://jpfhir.jp/fhir/eCS/StructureDefinition/JP_MedicationRequest_eCS"
            in r["meta"]["profile"]
        )


@pytest.mark.unit
class TestCategoryFilters:
    def test_vital_observation_no_clins_profile(self):
        r = {
            "resourceType": "Observation",
            "category": [{"coding": [{
                "system": "http://terminology.hl7.org/CodeSystem/observation-category",
                "code": "vital-signs",
            }]}],
        }
        _apply_jp_clins_profile(r)
        assert "meta" not in r or not r.get("meta", {}).get("profile")

    def test_lab_observation_gets_clins_profile(self):
        r = {
            "resourceType": "Observation",
            "category": [{"coding": [{
                "system": "http://terminology.hl7.org/CodeSystem/observation-category",
                "code": "laboratory",
            }]}],
        }
        _apply_jp_clins_profile(r)
        assert (
            "http://jpfhir.jp/fhir/eCS/StructureDefinition/JP_Observation_LabResult_eCS"
            in r["meta"]["profile"]
        )

    def test_diagnostic_report_no_clins_profile(self):
        # JP-CLINS v1.12.0 does not publish a DiagnosticReport profile.
        # Lab results are emitted only as Observation.LabResult in JP-CLINS.
        # The adapter must NOT attach a JP-CLINS profile to DiagnosticReport
        # regardless of category.
        r = {
            "resourceType": "DiagnosticReport",
            "category": [{"coding": [{
                "system": "http://terminology.hl7.org/CodeSystem/v2-0074",
                "code": "LAB",
            }]}],
        }
        _apply_jp_clins_profile(r)
        assert "meta" not in r or not r.get("meta", {}).get("profile")


@pytest.mark.unit
class TestIsLabObservation:
    def test_true_for_laboratory_category(self):
        r = {"category": [{"coding": [{"code": "laboratory"}]}]}
        assert _is_lab_observation(r) is True

    def test_false_for_vital_signs(self):
        r = {"category": [{"coding": [{"code": "vital-signs"}]}]}
        assert _is_lab_observation(r) is False

    def test_false_for_missing_category(self):
        assert _is_lab_observation({}) is False
