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

from clinosim.modules.output.fhir_r4_adapter import (
    _ECS_IDENTIFIER_SYSTEMS,
    _MEDIS_DISEASE_KEYNUMBER_SYSTEM,
    _MEDIS_UNCODED_DISEASE_CODE,
    _MEDIS_UNCODED_DISEASE_DISPLAY,
    _copy_display_from_sibling_coding,
    _populate_condition_ai_mr_ecs_fields,
    _populate_status_coding_display,
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
    assert not any(
        c.get("system") == _MEDIS_DISEASE_KEYNUMBER_SYSTEM for c in r["code"]["coding"]
    )


def test_jp_condition_medis_slice_creates_coding_list_when_empty():
    """Walker synthesises coding[] when Condition has code.text only."""
    r: dict = {"resourceType": "Condition", "id": "c1", "code": {"text": "本態性高血圧"}}
    _populate_condition_ai_mr_ecs_fields(r, country="JP")
    medis = [c for c in r["code"]["coding"] if c.get("system") == _MEDIS_DISEASE_KEYNUMBER_SYSTEM]
    assert len(medis) == 1
    assert medis[0]["code"] == _MEDIS_UNCODED_DISEASE_CODE


def test_condition_code_display_sibling_copy():
    """Primary coding lacks display (English-only CS strip); interop coding
    has the English display for the same code → propagate."""
    r: dict = {
        "resourceType": "Condition",
        "id": "c1",
        "code": {
            "coding": [
                {"system": "http://hl7.org/fhir/sid/icd-10", "code": "I10"},
                {
                    "system": "http://hl7.org/fhir/sid/icd-10",
                    "code": "I10",
                    "display": "Essential (primary) hypertension",
                },
            ],
            "text": "本態性(原発性)高血圧症",
        },
    }
    _populate_condition_ai_mr_ecs_fields(r)
    assert r["code"]["coding"][0]["display"] == "Essential (primary) hypertension"


# ---------------------------------------------------------------------------
# AllergyIntolerance
# ---------------------------------------------------------------------------


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


def test_allergy_reaction_manifestation_display_copy():
    """Reaction.manifestation coding gets sibling-copy display propagation too."""
    r: dict = {
        "resourceType": "AllergyIntolerance",
        "id": "a1",
        "reaction": [
            {
                "manifestation": [
                    {
                        "text": "発疹",
                        "coding": [
                            {"system": "http://snomed.info/sct", "code": "247472004"},
                            {"system": "http://snomed.info/sct", "code": "247472004", "display": "Rash"},
                        ],
                    }
                ]
            }
        ],
    }
    _populate_condition_ai_mr_ecs_fields(r)
    assert r["reaction"][0]["manifestation"][0]["coding"][0]["display"] == "Rash"


# ---------------------------------------------------------------------------
# MedicationRequest
# ---------------------------------------------------------------------------


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
# Sub-helper regression guards
# ---------------------------------------------------------------------------


def test_copy_display_from_sibling_coding_only_fills_missing():
    codings = [
        {"system": "sys1", "code": "X", "display": "Existing"},
        {"system": "sys2", "code": "X"},
    ]
    _copy_display_from_sibling_coding(codings)
    assert codings[0]["display"] == "Existing"  # unchanged
    assert codings[1]["display"] == "Existing"  # propagated


def test_copy_display_no_match_no_change():
    codings = [
        {"system": "sys1", "code": "X"},
        {"system": "sys2", "code": "Y"},
    ]
    _copy_display_from_sibling_coding(codings)
    assert "display" not in codings[0]
    assert "display" not in codings[1]


def test_populate_status_coding_display_unknown_code_untouched():
    """A code not in the display map is left alone (no fabrication)."""
    cd: dict = {"coding": [{"system": "hl7-cs", "code": "unknown-code-xyz"}]}
    _populate_status_coding_display(cd, {"active": "Active"})
    assert "display" not in cd["coding"][0]
