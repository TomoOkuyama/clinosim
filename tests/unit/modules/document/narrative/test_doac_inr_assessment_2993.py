"""An AF patient on a DOAC is not assessed against a warfarin INR target (Issue #2993)."""

from __future__ import annotations

from datetime import date, datetime
from types import SimpleNamespace

import pytest

from clinosim.locale.loader import load_chronic_followup
from clinosim.modules.document.narrative.template_generator import TemplateNarrativeGenerator
from clinosim.types.document import DocumentType, NarrativeContext
from clinosim.types.patient import ChronicCondition, HomeMedication, PatientProfile

pytestmark = pytest.mark.unit


def _lab(name: str, value: float, unit: str) -> SimpleNamespace:
    return SimpleNamespace(lab_name=name, value=value, unit=unit)


def _assessment(drug: str, labs: list, lang: str = "en") -> str:
    patient = PatientProfile(patient_id="pt-2993")
    patient.chronic_conditions = [ChronicCondition(code="I48.91")]
    patient.current_medications = [HomeMedication(drug_name=drug, route="PO")]
    patient.age = 74
    patient.sex = "F"
    patient.date_of_birth = date(1952, 1, 1)
    ctx = NarrativeContext(
        patient=patient,
        encounter=SimpleNamespace(encounter_id="enc-2993", admission_datetime=datetime(2026, 8, 1, 10)),
        encounter_type=None,
        disease_protocol=None,
        encounter_protocol=None,
        clinical_course_archetype="uncomplicated_improvement",
        severity="moderate",
        day_index=0,
        los_days=1,
        vitals=[],
        lab_results=labs,
        medications=[],
        diagnoses=[],
        procedures=[],
        allergies=[],
        document_type=DocumentType.OUTPATIENT_SOAP,
        target_lang=lang,
        locale="jp" if lang == "ja" else "us",
    )
    return TemplateNarrativeGenerator()._compose_chronic_assessment_integrated(ctx)


@pytest.mark.parametrize("lang", ["en", "ja"])
def test_an_apixaban_patients_note_has_no_inr_target_line(lang: str) -> None:
    text = _assessment("Apixaban", [_lab("PT-INR", 1.1, ""), _lab("eGFR", 58, "mL/min/1.73m2")], lang)
    assert "INR" not in text
    assert "2.0-3.0" not in text
    assert "eGFR 58" in text


def test_a_doac_note_reviews_renal_function_and_bleeding() -> None:
    text = _assessment("Rivaroxaban", [_lab("Creatinine", 1.1, "mg/dL"), _lab("Hb", 12.8, "g/dL")])
    assert "Cr 1.1 mg/dL" in text and "Hb 12.8 g/dL" in text
    assert "bleeding" in text


def test_a_warfarin_patients_note_keeps_the_inr_target() -> None:
    text = _assessment("Warfarin", [_lab("PT-INR", 1.6, "")])
    assert "PT-INR 1.6 — target 2.0-3.0 — subtherapeutic" in text


def test_the_af_follow_up_draws_no_routine_inr() -> None:
    """INR is drawn for warfarin through the medication monitoring table."""
    spec = load_chronic_followup()["I48"]
    assert "PT_INR" not in spec.get("labs", [])
    assert "INR" not in spec["visit_reason"]["en"]
