"""Issue #1776 — the outpatient Assessment section fell back to the
boilerplate "today's measurements (BP ... HR ...) not condition-specific;
defer <label> focused review to next visit." for 74% (197,168 / 263,652)
of populated narratives.

The phrase explicitly admits that no clinical reasoning fired. The
measurements it quotes are already present verbatim in the Objective
section, so the Assessment line adds zero clinical value AND teaches a
downstream LLM a procrastination pattern.

Fix: replace the ``obs_bits + followup_deferred`` fallback branch with
a structured-data fallback that reads the chronic condition's
``stage`` (populated by the longitudinal engine):

  * ``c.stage`` non-empty → ``"{label} ({stage}); management continued, no acute change this visit."``
  * ``c.stage`` empty      → ``"{label}: noted on problem list; no acute change this visit."``

Neither phrase re-quotes the vitals (which already live in Objective),
and neither tells the reader to defer the clinical judgement.
"""

from __future__ import annotations

from datetime import date, datetime
from types import SimpleNamespace

import pytest

from clinosim.modules.document.narrative.template_generator import TemplateNarrativeGenerator
from clinosim.types.document import DocumentType, NarrativeContext
from clinosim.types.patient import ChronicCondition, PatientProfile

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mk_ctx(chronic_code: str, chronic_stage: str, lang: str = "en") -> NarrativeContext:
    patient = PatientProfile(patient_id="pt-1776")
    patient.chronic_conditions = [
        ChronicCondition(code=chronic_code, stage=chronic_stage),
    ]
    patient.current_medications = []
    patient.age = 14
    patient.sex = "M"
    patient.date_of_birth = date(2010, 1, 1)
    vital = SimpleNamespace(
        systolic_bp=108,
        diastolic_bp=60,
        heart_rate=70,
        temperature_celsius=36.6,
        spo2=98.0,
        respiratory_rate=None,
    )
    encounter = SimpleNamespace(
        encounter_id="enc-1776",
        admission_datetime=datetime(2026, 8, 1, 10, 0),
    )
    return NarrativeContext(
        patient=patient,
        encounter=encounter,
        encounter_type=None,
        disease_protocol=None,
        encounter_protocol=None,
        clinical_course_archetype="uncomplicated_improvement",
        severity="moderate",
        day_index=0,
        los_days=0,
        vitals=[vital],
        lab_results=[],
        medications=[],
        diagnoses=[],
        procedures=[],
        allergies=[],
        document_type=DocumentType.OUTPATIENT_SOAP,
        target_lang=lang,
        locale="jp" if lang == "ja" else "us",
    )


def _run(ctx: NarrativeContext) -> str:
    return TemplateNarrativeGenerator()._compose_chronic_assessment_integrated(ctx)


# ---------------------------------------------------------------------------
# Repro: the pre-fix boilerplate must disappear
# ---------------------------------------------------------------------------


def test_fallback_does_not_emit_not_condition_specific_boilerplate_en():
    text = _run(_mk_ctx("G47.30", "moderate", lang="en"))
    assert "not condition-specific" not in text, (
        f"Expected the structured-data fallback to replace the pre-fix boilerplate, got: {text!r}"
    )
    assert "focused review" not in text.lower(), (
        f"The deferral clause must not appear in the structured-data fallback: {text!r}"
    )


def test_fallback_does_not_emit_not_condition_specific_boilerplate_ja():
    text = _run(_mk_ctx("G47.30", "moderate", lang="ja"))
    assert "病態特異的" not in text, f"JP boilerplate must not fire: {text!r}"
    assert "特化評価" not in text, f"JP boilerplate must not fire: {text!r}"


def test_fallback_does_not_requote_vitals_in_assessment():
    """The pre-fix boilerplate re-cited BP / HR / T / SpO2 from the
    Objective section inside the Assessment. The structured-data
    fallback must not do that — the Objective section already carries
    them and the duplication is what made the dataset read as 74%
    hollow."""
    text = _run(_mk_ctx("G47.30", "moderate", lang="en"))
    assert "BP 108/60" not in text, f"vitals must stay in Objective: {text!r}"
    assert "HR 70" not in text, f"vitals must stay in Objective: {text!r}"


# ---------------------------------------------------------------------------
# Positive content: structured data surfaces instead
# ---------------------------------------------------------------------------


def test_stage_bearing_chronic_surfaces_the_stage():
    text = _run(_mk_ctx("G47.30", "moderate", lang="en"))
    assert "moderate" in text, f"stage must surface in the structured fallback: {text!r}"


def test_stage_less_chronic_falls_back_to_noted_stub():
    text = _run(_mk_ctx("G47.30", "", lang="en"))
    assert text, f"stage-less chronic must still produce an Assessment line: {text!r}"
    assert "not condition-specific" not in text
    assert "problem list" in text.lower() or "no acute" in text.lower(), (
        f"stage-less fallback must indicate a benign status, got: {text!r}"
    )


# ---------------------------------------------------------------------------
# Backward compat: I10-specific branch still fires when today's BP is
# elevated — the structured-data fallback must not displace a tailored
# condition-specific branch.
# ---------------------------------------------------------------------------


def test_condition_specific_branch_still_fires_for_i10():
    """Patient with I10 and today's BP 152/94 should still render the
    hypertension-specific prose, not the stub."""
    patient = PatientProfile(patient_id="pt-i10")
    patient.chronic_conditions = [ChronicCondition(code="I10", stage="")]
    patient.current_medications = []
    patient.age = 55
    patient.sex = "F"
    patient.date_of_birth = date(1970, 1, 1)
    vital = SimpleNamespace(
        systolic_bp=152,
        diastolic_bp=94,
        heart_rate=78,
        temperature_celsius=36.7,
        spo2=97.0,
        respiratory_rate=None,
    )
    ctx = NarrativeContext(
        patient=patient,
        encounter=SimpleNamespace(encounter_id="enc", admission_datetime=datetime(2026, 8, 1)),
        encounter_type=None,
        disease_protocol=None,
        encounter_protocol=None,
        clinical_course_archetype="uncomplicated_improvement",
        severity="moderate",
        day_index=0,
        los_days=0,
        vitals=[vital],
        lab_results=[],
        medications=[],
        diagnoses=[],
        procedures=[],
        allergies=[],
        document_type=DocumentType.OUTPATIENT_SOAP,
        target_lang="en",
        locale="us",
    )
    text = _run(ctx)
    assert "152/94" in text, f"I10-specific branch must still cite SBP/DBP: {text!r}"
