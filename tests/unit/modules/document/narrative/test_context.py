"""NarrativeContext factory tests."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from clinosim.modules.document.narrative.context import build_narrative_context
from clinosim.types.document import DocumentType
from clinosim.types.patient import PatientProfile


def _make_record() -> SimpleNamespace:
    record = SimpleNamespace(
        patient=PatientProfile(patient_id="pt1"),
        encounters=[],
        documents=[],
        extensions={},
    )
    return record


def test_build_context_for_admission_hp() -> None:
    record = _make_record()
    encounter = SimpleNamespace(
        encounter_id="enc1",
        encounter_type=SimpleNamespace(value="inpatient"),
        admission_datetime=datetime(2026, 7, 1, 10, 0),
    )
    ctx = build_narrative_context(
        record=record,
        encounter=encounter,
        document_type=DocumentType.ADMISSION_HP,
        day_index=0,
        country="jp",
        disease_protocol=None,
        encounter_protocol=None,
        clinical_course_archetype="uncomplicated_improvement",
        severity="moderate",
        los_days=5,
    )
    assert ctx.document_type == DocumentType.ADMISSION_HP
    assert ctx.day_index == 0
    assert ctx.target_lang == "ja"
    assert ctx.locale == "jp"
    assert ctx.allergies == []


def test_build_context_us_locale() -> None:
    record = _make_record()
    encounter = SimpleNamespace(
        encounter_id="enc2",
        encounter_type=SimpleNamespace(value="inpatient"),
        admission_datetime=datetime(2026, 7, 1, 10, 0),
    )
    ctx = build_narrative_context(
        record=record,
        encounter=encounter,
        document_type=DocumentType.PROGRESS_NOTE,
        day_index=2,
        country="us",
    )
    assert ctx.target_lang == "en"
    assert ctx.locale == "us"
    assert ctx.day_index == 2
    assert ctx.document_type == DocumentType.PROGRESS_NOTE


def test_build_context_empty_lists_when_no_data() -> None:
    """Record without optional fields defaults to empty lists."""
    record = SimpleNamespace(patient=None)
    encounter = SimpleNamespace(
        encounter_id="enc3",
        encounter_type=None,
        admission_datetime=datetime(2026, 7, 1, 10, 0),
    )
    ctx = build_narrative_context(
        record=record,
        encounter=encounter,
        document_type=DocumentType.DISCHARGE_SUMMARY,
        day_index=5,
        country="us",
    )
    assert ctx.allergies == []
    assert ctx.vitals == []
    assert ctx.lab_results == []
    assert ctx.medications == []
    assert ctx.diagnoses == []
    assert ctx.procedures == []
