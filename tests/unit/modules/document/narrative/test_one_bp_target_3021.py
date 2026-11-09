"""Issue #3021: a hypertension note states one BP target and judges control against it.

JSH 2019: < 130/80 mmHg for adults under 75 (and for older patients with
diabetes or coronary artery disease), < 140/90 mmHg from 75.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from clinosim.modules.document.narrative.template_generator import TemplateNarrativeGenerator
from clinosim.types.document import DocumentType, NarrativeContext
from clinosim.types.patient import ChronicCondition, PatientProfile

pytestmark = pytest.mark.unit


def _assessment(age: int, sbp: int, dbp: int, codes: tuple[str, ...] = ("I10",), lang: str = "ja") -> str:
    patient = PatientProfile(patient_id="pt-3021")
    patient.chronic_conditions = [ChronicCondition(code=c) for c in codes]
    patient.age = age
    patient.sex = "M"
    ctx = NarrativeContext(
        patient=patient,
        encounter=SimpleNamespace(encounter_id="enc-3021", admission_datetime=datetime(2026, 8, 1, 10)),
        encounter_type=None,
        disease_protocol=None,
        encounter_protocol=None,
        clinical_course_archetype="uncomplicated_improvement",
        severity="moderate",
        day_index=0,
        los_days=1,
        vitals=[SimpleNamespace(systolic_bp=sbp, diastolic_bp=dbp, heart_rate=72, temperature_celsius=36.5, spo2=98)],
        lab_results=[],
        medications=[],
        diagnoses=[],
        procedures=[],
        allergies=[],
        document_type=DocumentType.OUTPATIENT_SOAP,
        target_lang=lang,
        locale="jp" if lang == "ja" else "us",
    )
    return TemplateNarrativeGenerator()._compose_chronic_assessment_integrated(ctx)


def test_a_60_year_olds_note_states_only_130_80() -> None:
    text = _assessment(60, 135, 82)
    assert "目標 130/80 mmHg 未満" in text
    assert "140/90" not in text
    assert "目標達成" not in text


def test_a_bp_below_the_target_is_at_goal() -> None:
    assert "目標達成" in _assessment(60, 124, 76)


def test_a_78_year_olds_target_is_140_90() -> None:
    text = _assessment(78, 135, 82)
    assert "目標 140/90 mmHg 未満" in text and "130/80" not in text
    assert "目標達成" in text


def test_a_78_year_old_with_diabetes_keeps_130_80() -> None:
    assert "目標 130/80 mmHg 未満" in _assessment(78, 135, 82, ("I10", "E11.9"))


def test_the_hypertension_template_seed_states_no_target_number() -> None:
    seed = yaml.safe_load(
        Path("clinosim/modules/document/reference_data/chronic_soap_templates.yaml").read_text(encoding="utf-8")
    )["I10"]
    assert "130/80" not in str(seed) and "140/90" not in str(seed)
