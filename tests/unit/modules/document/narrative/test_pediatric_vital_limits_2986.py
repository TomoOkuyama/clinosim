"""A child's SOAP Assessment judges heart rate by the age range (Issue #2986)."""

from __future__ import annotations

from datetime import date, datetime
from types import SimpleNamespace

import pytest

from clinosim.modules.document.narrative.template_generator import TemplateNarrativeGenerator
from clinosim.modules.observation.pediatric_ranges import age_in_completed_months, pediatric_vital_range
from clinosim.types.document import DocumentType, NarrativeContext
from clinosim.types.patient import PatientProfile

pytestmark = pytest.mark.unit

_VISIT = datetime(2026, 8, 1, 10, 0)


def _assessment(dob: date, hr: float, lang: str = "en") -> str:
    patient = PatientProfile(patient_id="pt-2986")
    patient.chronic_conditions = []
    patient.current_medications = []
    patient.age = max(0, _VISIT.year - dob.year)
    patient.sex = "M"
    patient.date_of_birth = dob
    vital = SimpleNamespace(
        systolic_bp=None,
        diastolic_bp=None,
        heart_rate=hr,
        temperature_celsius=None,
        spo2=None,
        respiratory_rate=None,
        timestamp=_VISIT,
    )
    ctx = NarrativeContext(
        patient=patient,
        encounter=SimpleNamespace(encounter_id="enc-2986", admission_datetime=_VISIT),
        encounter_type=None,
        disease_protocol=None,
        encounter_protocol=None,
        clinical_course_archetype="uncomplicated_improvement",
        severity="moderate",
        day_index=0,
        los_days=1,
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
    return TemplateNarrativeGenerator()._compose_chronic_assessment_integrated(ctx)


@pytest.mark.parametrize("lang", ["en", "ja"])
def test_hr_136_at_5_days_gives_no_tachycardia_line(lang: str) -> None:
    text = _assessment(date(2026, 7, 27), 136, lang)
    assert "136" not in text


def test_hr_110_at_30_years_still_gives_a_tachycardia_line() -> None:
    assert "Tachycardia: HR 110" in _assessment(date(1996, 1, 1), 110)


def test_hr_above_the_age_range_gives_a_tachycardia_line() -> None:
    dob = date(2024, 6, 1)  # 2 years old
    high = pediatric_vital_range("heart_rate", age_in_completed_months(dob, _VISIT)).high
    assert "Tachycardia" not in _assessment(dob, high)
    assert f"Tachycardia: HR {int(high) + 5}" in _assessment(dob, high + 5)
