"""Unit tests for `_populate_condition_ai_mr_ecs_fields` walker.

JP-CLINS eCS profiles (`JP_Condition_eCS`, `JP_AllergyIntolerance_eCS`,
`JP_MedicationRequest_eCS`) declare `identifier`, `meta.lastUpdated`, and
require `clinicalStatus.coding.display` + `verificationStatus.coding.display`
+ `code.coding[].display` on the primary coding. The walker is a single seam
running universally (base FHIR admits these as optional; JP eCS requires
them; US output picks them up harmlessly).

Feedback fix (2026-07-16, PR-G).
"""

from __future__ import annotations

import pytest

from clinosim.modules.output.fhir_r4.post_process import (
    _ECS_IDENTIFIER_SYSTEMS,
    _MEDIS_DISEASE_KEYNUMBER_SYSTEM,
    _MEDIS_UNCODED_DISEASE_CODE,
    _MEDIS_UNCODED_DISEASE_DISPLAY,
    _populate_condition_ai_mr_ecs_fields,
)

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Condition
# ---------------------------------------------------------------------------


def test_condition_identifier_populated_from_id():
    r: dict = {"resourceType": "Condition", "id": "cond-x-1", "recordedDate": "2025-06-11"}
    _populate_condition_ai_mr_ecs_fields(r)
    assert r["identifier"] == [{"system": _ECS_IDENTIFIER_SYSTEMS["Condition"], "value": "cond-x-1"}]


def test_condition_meta_lastupdated_from_recordeddate():
    r: dict = {"resourceType": "Condition", "id": "c1", "recordedDate": "2025-06-11", "onsetDateTime": "2014-11-02"}
    _populate_condition_ai_mr_ecs_fields(r)
    # recordedDate wins over onsetDateTime (record-lifecycle, not clinical onset)
    assert r["meta"]["lastUpdated"] == "2025-06-11"


def test_condition_meta_lastupdated_falls_back_to_onset_when_no_recorded():
    r: dict = {"resourceType": "Condition", "id": "c1", "onsetDateTime": "2014-11-02"}
    _populate_condition_ai_mr_ecs_fields(r)
    assert r["meta"]["lastUpdated"] == "2014-11-02"


def test_condition_clinical_status_display_active():
    r: dict = {
        "resourceType": "Condition",
        "id": "c1",
        "clinicalStatus": {"coding": [{"system": "hl7-cs", "code": "active"}]},
    }
    _populate_condition_ai_mr_ecs_fields(r)
    assert r["clinicalStatus"]["coding"][0]["display"] == "Active"


def test_condition_verification_status_display_confirmed():
    r: dict = {
        "resourceType": "Condition",
        "id": "c1",
        "verificationStatus": {"coding": [{"system": "hl7-cs", "code": "confirmed"}]},
    }
    _populate_condition_ai_mr_ecs_fields(r)
    assert r["verificationStatus"]["coding"][0]["display"] == "Confirmed"


def test_jp_condition_gains_medis_recordno_slice():
    """JP output: walker appends the MEDIS 病名管理番号 coding (uncoded placeholder)
    so `JP_Condition_eCS` `code.coding:medisRecordNo` slice min=1 is satisfied."""
    r: dict = {
        "resourceType": "Condition",
        "id": "c1",
        "code": {
            "coding": [
                {"system": "http://hl7.org/fhir/sid/icd-10", "code": "I10", "display": "本態性(原発性)高血圧症"},
            ],
        },
    }
    _populate_condition_ai_mr_ecs_fields(r, country="JP")
    codings = r["code"]["coding"]
    medis = [c for c in codings if c.get("system") == _MEDIS_DISEASE_KEYNUMBER_SYSTEM]
    assert len(medis) == 1
    assert medis[0]["code"] == _MEDIS_UNCODED_DISEASE_CODE
    assert medis[0]["display"] == _MEDIS_UNCODED_DISEASE_DISPLAY


def test_jp_condition_medis_slice_idempotent():
    """Walker skips when a MEDIS coding already exists — supports future
    per-ICD-10 curation without duplication."""
    existing = {
        "system": _MEDIS_DISEASE_KEYNUMBER_SYSTEM,
        "code": "20050020",
        "display": "２型糖尿病",
    }
    r: dict = {
        "resourceType": "Condition",
        "id": "c1",
        "code": {"coding": [{"system": "http://hl7.org/fhir/sid/icd-10", "code": "E11.9"}, existing]},
    }
    _populate_condition_ai_mr_ecs_fields(r, country="JP")
    medis = [c for c in r["code"]["coding"] if c.get("system") == _MEDIS_DISEASE_KEYNUMBER_SYSTEM]
    assert medis == [existing]


def test_us_condition_does_not_gain_medis_slice():
    """MEDIS is JP-only — US Condition must not receive the coding."""
    r: dict = {
        "resourceType": "Condition",
        "id": "c1",
        "code": {"coding": [{"system": "http://hl7.org/fhir/sid/icd-10-cm", "code": "I10"}]},
    }
    _populate_condition_ai_mr_ecs_fields(r, country="US")
    assert not any(c.get("system") == _MEDIS_DISEASE_KEYNUMBER_SYSTEM for c in r["code"]["coding"])


def test_jp_condition_medis_slice_creates_coding_list_when_empty():
    """Walker synthesises coding[] when Condition has code.text only."""
    r: dict = {"resourceType": "Condition", "id": "c1", "code": {"text": "本態性高血圧"}}
    _populate_condition_ai_mr_ecs_fields(r, country="JP")
    medis = [c for c in r["code"]["coding"] if c.get("system") == _MEDIS_DISEASE_KEYNUMBER_SYSTEM]
    assert len(medis) == 1
    assert medis[0]["code"] == _MEDIS_UNCODED_DISEASE_CODE


def test_allergy_identifier_populated_from_id():
    r: dict = {"resourceType": "AllergyIntolerance", "id": "allergy-x-1"}
    _populate_condition_ai_mr_ecs_fields(r)
    assert r["identifier"] == [{"system": _ECS_IDENTIFIER_SYSTEMS["AllergyIntolerance"], "value": "allergy-x-1"}]


def test_allergy_status_displays_populated():
    r: dict = {
        "resourceType": "AllergyIntolerance",
        "id": "a1",
        "clinicalStatus": {"coding": [{"system": "hl7-cs", "code": "active"}]},
        "verificationStatus": {"coding": [{"system": "hl7-cs", "code": "unconfirmed"}]},
    }
    _populate_condition_ai_mr_ecs_fields(r)
    assert r["clinicalStatus"]["coding"][0]["display"] == "Active"
    assert r["verificationStatus"]["coding"][0]["display"] == "Unconfirmed"


def test_medication_request_meta_lastupdated_from_authored_on():
    r: dict = {"resourceType": "MedicationRequest", "id": "mr1", "authoredOn": "2025-11-25T14:24:00+09:00"}
    _populate_condition_ai_mr_ecs_fields(r)
    assert r["meta"]["lastUpdated"] == "2025-11-25T14:24:00+09:00"


def test_medication_request_identifier_not_overwritten():
    """MedicationRequest is NOT in _ECS_IDENTIFIER_SYSTEMS — its builder
    already emits rpNumber + orderInRp identifier slices (session 51 rule)."""
    pre = [{"system": "http://jpfhir.jp/...RPGroupNumber", "value": "1"}]
    r: dict = {"resourceType": "MedicationRequest", "id": "mr1", "identifier": pre}
    _populate_condition_ai_mr_ecs_fields(r)
    assert r["identifier"] == pre  # unchanged


# ---------------------------------------------------------------------------
# Idempotency + safety
# ---------------------------------------------------------------------------


def test_idempotent_second_pass_leaves_populated_fields_alone():
    r: dict = {
        "resourceType": "Condition",
        "id": "c1",
        "recordedDate": "2025-06-11",
        "clinicalStatus": {"coding": [{"system": "hl7-cs", "code": "active"}]},
    }
    _populate_condition_ai_mr_ecs_fields(r)
    before = {
        "identifier": list(r.get("identifier", [])),
        "lastUpdated": r["meta"].get("lastUpdated"),
        "display": r["clinicalStatus"]["coding"][0].get("display"),
    }
    _populate_condition_ai_mr_ecs_fields(r)
    assert r.get("identifier") == before["identifier"]
    assert r["meta"].get("lastUpdated") == before["lastUpdated"]
    assert r["clinicalStatus"]["coding"][0].get("display") == before["display"]


def test_ignores_unrelated_resource_types():
    r: dict = {"resourceType": "Patient", "id": "pt1"}
    _populate_condition_ai_mr_ecs_fields(r)
    assert "identifier" not in r
    assert "meta" not in r


def test_no_datetime_source_no_lastupdated():
    r: dict = {"resourceType": "Condition", "id": "c1"}
    _populate_condition_ai_mr_ecs_fields(r)
    assert "lastUpdated" not in r.get("meta", {})


# ---------------------------------------------------------------------------
# Issue #2520: JP-CLINS resourceIdentifier slice on builder-set identifiers
# ---------------------------------------------------------------------------

_RESOURCE_INSTANCE = "http://jpfhir.jp/fhir/core/IdSystem/resourceInstance-identifier"
_BUILDER_ID = {"system": "urn:clinosim:condition-key", "value": "K1"}


@pytest.mark.parametrize("rt", ["Condition", "AllergyIntolerance"])
def test_jp_slice_is_prepended_to_a_builder_set_identifier(rt):
    r = {"resourceType": rt, "id": "X1", "identifier": [dict(_BUILDER_ID)]}
    _populate_condition_ai_mr_ecs_fields(r, country="JP")
    assert r["identifier"] == [{"system": _RESOURCE_INSTANCE, "value": "X1"}, _BUILDER_ID]


@pytest.mark.parametrize("rt", ["Condition", "AllergyIntolerance"])
def test_jp_slice_is_added_once(rt):
    r = {"resourceType": rt, "id": "X1", "identifier": [dict(_BUILDER_ID)]}
    _populate_condition_ai_mr_ecs_fields(r, country="JP")
    _populate_condition_ai_mr_ecs_fields(r, country="JP")
    assert sum(i["system"] == _RESOURCE_INSTANCE for i in r["identifier"]) == 1


@pytest.mark.parametrize("rt", ["Condition", "AllergyIntolerance"])
def test_us_builder_identifier_is_left_alone(rt):
    r = {"resourceType": rt, "id": "X1", "identifier": [dict(_BUILDER_ID)]}
    _populate_condition_ai_mr_ecs_fields(r, country="US")
    assert r["identifier"] == [_BUILDER_ID]


def test_jp_empty_identifier_gets_slice_then_internal_namespace():
    r = {"resourceType": "Condition", "id": "X1"}
    _populate_condition_ai_mr_ecs_fields(r, country="JP")
    assert r["identifier"] == [
        {"system": _RESOURCE_INSTANCE, "value": "X1"},
        {"system": _ECS_IDENTIFIER_SYSTEMS["Condition"], "value": "X1"},
    ]
