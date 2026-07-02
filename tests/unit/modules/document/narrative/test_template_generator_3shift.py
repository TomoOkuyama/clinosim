"""Unit tests for NURSING_SHIFT_NOTE shift labeling in Stage 2 rendering (α-min-3).

The structural stub carries a neutral shift key ("night"/"day"/"evening",
`ClinicalDocument.shift` → `NarrativeContext.shift`). The template generator
resolves the localized label at render time (AD-30 spirit — labels are never
baked into structural CIF):
  en: night / day / evening
  ja: 深夜 / 日勤 / 準夜
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from typing import Any

import pytest

from clinosim.modules.document.engine import SHIFT_SCHEDULE
from clinosim.modules.document.narrative.registry import DocumentTypeSpec
from clinosim.modules.document.narrative.template_generator import (
    _SHIFT_LABELS_EN,
    _SHIFT_LABELS_JA,
    TemplateNarrativeGenerator,
)
from clinosim.types.document import DocumentType, FormatType, NarrativeContext
from clinosim.types.patient import PatientProfile

pytestmark = pytest.mark.unit


def _make_patient() -> PatientProfile:
    patient = PatientProfile(patient_id="pt-3shift-test")
    patient.chronic_conditions = []
    patient.current_medications = []
    patient.allergies = []
    return patient


def _make_encounter(primary_nurse_id: str = "") -> Any:
    return SimpleNamespace(
        encounter_id="enc-3shift-test",
        encounter_type=SimpleNamespace(value="inpatient"),
        admission_datetime=datetime(2026, 7, 1, 10, 0),
        triage_data=None,
        primary_nurse_id=primary_nurse_id,
    )


def _make_ctx(
    shift: str,
    target_lang: str = "ja",
    locale: str = "jp",
    day_index: int = 1,
) -> NarrativeContext:
    return NarrativeContext(
        patient=_make_patient(),
        encounter=_make_encounter(),
        encounter_type=SimpleNamespace(value="inpatient"),
        disease_protocol=None,
        encounter_protocol=None,
        clinical_course_archetype="uncomplicated_improvement",
        severity="moderate",
        day_index=day_index,
        los_days=5,
        vitals=[],
        lab_results=[],
        medications=[],
        diagnoses=[],
        procedures=[],
        allergies=[],
        document_type=DocumentType.NURSING_SHIFT_NOTE,
        target_lang=target_lang,
        locale=locale,
        shift=shift,
    )


def _make_spec() -> DocumentTypeSpec:
    return DocumentTypeSpec(
        type_key="nursing_shift_note",
        loinc_code="34746-8",
        format_type=FormatType.FREE_TEXT,
        countries_supported=("jp", "us"),
        generation_frequency="daily_3shift",
    )


def _render(shift: str, target_lang: str, locale: str) -> str:
    gen = TemplateNarrativeGenerator()
    out = gen.generate(_make_ctx(shift, target_lang=target_lang, locale=locale), _make_spec())
    return out.raw_text


# ─── Label resolution ────────────────────────────────────────────────────────


def test_ja_shift_labels_rendered() -> None:
    """JP locale: 日勤 / 準夜 / 深夜 labels in raw_text per shift key."""
    assert "日勤" in _render("day", "ja", "jp")
    assert "準夜" in _render("evening", "ja", "jp")
    assert "深夜" in _render("night", "ja", "jp")


def test_en_shift_labels_rendered() -> None:
    """US locale: day / evening / night labels in raw_text per shift key."""
    assert "day" in _render("day", "en", "us").lower()
    assert "evening" in _render("evening", "en", "us").lower()
    assert "night" in _render("night", "en", "us").lower()


def test_three_shifts_produce_distinct_text_ja() -> None:
    """The 3 per-day JP notes must differ at least by the shift label."""
    texts = {_render(s, "ja", "jp") for s in ("night", "day", "evening")}
    assert len(texts) == 3, "JP shift notes for the same day must be pairwise distinct"


def test_three_shifts_produce_distinct_text_en() -> None:
    """The 3 per-day US notes must differ at least by the shift label."""
    texts = {_render(s, "en", "us") for s in ("night", "day", "evening")}
    assert len(texts) == 3, "EN shift notes for the same day must be pairwise distinct"


def test_neutral_key_not_leaked_in_ja_text() -> None:
    """JP note shows the translated label, not the raw English key (AD-30 spirit)."""
    text = _render("evening", "ja", "jp")
    assert "evening" not in text, f"raw shift key leaked into JP text: {text!r}"


def test_empty_shift_backward_compatible() -> None:
    """shift == '' (non-3shift callers) keeps producing non-empty text, no label."""
    for lang, locale in (("ja", "jp"), ("en", "us")):
        text = _render("", lang, locale)
        assert text.strip() != ""
        for label in ("日勤", "準夜", "深夜"):
            assert label not in text


def test_shift_fact_tracked_in_facts_used() -> None:
    """facts_used must record ctx.shift when a shift key is present."""
    gen = TemplateNarrativeGenerator()
    out = gen.generate(_make_ctx("day"), _make_spec())
    assert "ctx.shift" in out.facts_used


def test_shift_key_recorded_in_metadata() -> None:
    """NarrativeOutput.metadata carries the neutral shift key for auditability."""
    gen = TemplateNarrativeGenerator()
    out = gen.generate(_make_ctx("night"), _make_spec())
    assert out.metadata.get("shift") == "night"


# ─── Single-source-of-truth guard ────────────────────────────────────────────


def test_label_maps_cover_all_schedule_shift_keys() -> None:
    """Both label maps must cover exactly the SHIFT_SCHEDULE keys (engine = writer)."""
    schedule_keys = {k for k, _ in SHIFT_SCHEDULE}
    assert set(_SHIFT_LABELS_JA) == schedule_keys
    assert set(_SHIFT_LABELS_EN) == schedule_keys
