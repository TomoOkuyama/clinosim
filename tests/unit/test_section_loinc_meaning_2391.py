"""Every Composition section code means its section (Issue #2391).

``_REVIEWED`` is the reviewed section → LOINC table (tx.fhir.org ``$lookup``,
2026-11-01): a change to a section's code must update it here, with the code's
LOINC meaning checked. ``""`` = no LOINC section code means the section.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import clinosim
from clinosim.datafiles import load_data_yaml

pytestmark = pytest.mark.unit

_ROOT = Path(clinosim.__file__).parent
_CATALOG = load_data_yaml(_ROOT / "modules/document/reference_data/section_catalog.yaml")
_LOINC = load_data_yaml(_ROOT / "codes/data/loinc.yaml")["codes"]
_SNAPSHOT = {
    c["code"]: c
    for c in json.loads((_ROOT / "codes/authoritative/loinc_2_83_tx.json").read_text(encoding="utf-8"))["concept"]
}

_REVIEWED = {
    "subjective": "61150-9",
    "objective": "61149-1",
    "assessment": "51848-0",
    "plan": "18776-5",
    "chief_complaint": "10154-3",
    "hpi": "10164-2",
    "past_medical_history": "11348-0",
    "medications_at_home": "10160-0",
    "physical_exam": "29545-1",
    "physical_examination": "29545-1",
    "triage_details": "",
    "assessment_and_plan": "51847-2",
    "admission_reason": "29299-5",
    "admission_details": "",
    "admission_diagnoses": "46241-6",
    "admission_state": "",
    "admission_status": "",
    "admission_summary": "",
    "hospital_course": "8648-8",
    "discharge_diagnoses": "11535-2",
    "discharge_details": "",
    "discharge_medications": "10183-2",
    "discharge_evaluation": "",
    "discharge_readiness": "",
    "discharge_estimate": "",
    "discharge_instructions": "8653-8",
    "nursing_history": "",
    "nursing_diagnosis": "",
    "nursing_interventions_provided": "62387-6",
    "adl_assessment": "47420-5",
    "risk_assessments": "",
    "care_plan": "64295-9",
    "reassessment_timing": "18776-5",
    "other_issues": "",
    "ward_and_room": "",
    "ward_and_physician": "",
    "other_staff": "85847-2",
    "diagnosis": "29308-4",
    "symptoms": "10187-3",
    "patient_and_diagnosis": "29308-4",
    "dietitian": "85847-2",
    "nutrition_risk": "61144-2",
    "nutrition_assessment": "61144-2",
    "nutrition_goals": "61144-2",
    "nutrition_supply": "61144-2",
    "nutrition_counseling": "61144-2",
    "dietary_content": "61144-2",
    "dysphagia_diet": "61144-2",
    "allergies": "48765-2",
    "family_history": "10157-6",
    "social_history": "29762-2",
    "patient_education": "34895-3",
    "ed_workup": "30954-2",
    "disposition": "8650-4",
    "treatment_plan": "18776-5",
    "test_schedule": "18776-5",
    "surgery_schedule": "18776-5",
    "special_nutrition_management": "61144-2",
    "other_plans": "18776-5",
    "estimated_los": "",
    "explanation_consent": "",
    "session_frequency": "18776-5",
    "rehab_team": "85847-2",
    "policy": "18776-5",
    "goals": "61146-7",
    "functional_status": "47420-5",
    "basic_movement": "47420-5",
    "immediate_cause_of_death": "69453-9",
    "underlying_cause_of_death": "69453-9",
    "contributing_conditions": "69453-9",
    "duration_of_immediate_cause": "69440-6",
    "manner_of_death": "69449-7",
    "circumstances_of_death": "",
    "cause_of_death": "69453-9",
    "autopsy_status": "85699-7",
    "autopsy_status_and_findings": "85699-7",
    "treatment_course": "8648-8",
    "terminal_course": "8648-8",
    "complications_and_comorbidities": "",
    "family_communication": "",
    "op_procedure_name": "29554-3",
    "op_anesthesia": "59774-0",
    "op_surgeon": "85847-2",
    "op_findings": "59776-5",
    "op_course": "29554-3",
    "op_specimens": "59773-2",
    "op_blood_loss": "59770-8",
    "op_equipment": "29554-3",
    "op_postop_plan": "18776-5",
    "pn_procedure_name": "29554-3",
    "pn_consent": "29554-3",
    "pn_performer": "85847-2",
    "pn_analgesia": "59774-0",
    "pn_course": "29554-3",
    "pn_complications": "55109-3",
    "pn_specimens": "59773-2",
    "pn_postop_plan": "18776-5",
    "referring_institution": "",
    "referral_destination": "",
    "referral_purpose": "42349-1",
    "present_illness": "10164-2",
    "present_illness_ref": "10164-2",
    "checkup_questionnaire": "",
    "checkup_lab_results": "30954-2",
    "diagnoses_and_complaint": "29308-4",
    "follow_up": "18776-5",
}

# Codes that mean something other than any section they were used for.
_WRONG_MEANING = {
    "51897-7": "Healthcare Associated Infection report Document",
    "51852-2": "Letter",
    "8646-2": "Hospital admission diagnosis",
    "8649-6": "Hospital discharge date",
    "75326-9": "Problem",
    "68609-7": "Hospital Letter",
}


def test_catalog_matches_the_reviewed_table() -> None:
    assert {k: v["loinc"] for k, v in _CATALOG.items()} == _REVIEWED


@pytest.mark.parametrize("code", sorted({c for c in _REVIEWED.values() if c}))
def test_section_code_is_registered_and_active(code: str) -> None:
    # Display wording is governed by the LOINC registry tests (Issue #2260).
    assert _LOINC[code]["en"]
    assert _SNAPSHOT[code]["status"] == "ACTIVE"


def test_no_section_uses_a_code_of_another_meaning() -> None:
    used = {slug: code for slug, code in _REVIEWED.items() if code in _WRONG_MEANING}
    assert not used, used


def test_operative_note_sections_use_the_operative_note_codes() -> None:
    assert _REVIEWED["op_anesthesia"] == "59774-0"  # Procedure anesthesia Narrative
    assert _REVIEWED["op_specimens"] == _REVIEWED["pn_specimens"] == "59773-2"
    assert _REVIEWED["op_blood_loss"] == "59770-8"  # Procedure estimated blood loss
    assert _REVIEWED["op_findings"] == "59776-5"  # Procedure findings
    assert _REVIEWED["pn_complications"] == "55109-3"  # Complications
    assert _REVIEWED["op_surgeon"] == _REVIEWED["pn_performer"] == "85847-2"  # Care team
