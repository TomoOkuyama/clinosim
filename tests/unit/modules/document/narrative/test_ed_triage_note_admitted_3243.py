"""Issue #3243: the triage note of a patient admitted through the ED.

An admission's ``chief_complaint`` is English (the localized text is on
``chief_complaint_<lang>``), so the note reads the complaint in its own
language from the encounter and falls back to the triage summary.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from clinosim.modules.document.narrative.renderers.ed_triage_note import render_ed_triage_note
from clinosim.types.triage import TriageData

pytestmark = pytest.mark.unit


def _ctx(lang: str, **enc_fields: str) -> SimpleNamespace:
    triage = TriageData(
        level="2", level_system="JTAS", arrival_mode="ambulance", chief_complaint_summary="Fever, cough"
    )
    return SimpleNamespace(target_lang=lang, encounter=SimpleNamespace(triage_data=triage, **enc_fields))


def test_ja_note_of_an_admission_uses_the_japanese_chief_complaint() -> None:
    out = render_ed_triage_note(_ctx("ja", chief_complaint="Fever, cough", chief_complaint_ja="発熱・咳嗽"), None)
    assert "発熱・咳嗽" in out.raw_text and "Fever" not in out.raw_text, out.raw_text


def test_en_note_keeps_the_triage_summary() -> None:
    out = render_ed_triage_note(_ctx("en", chief_complaint="Fever, cough", chief_complaint_ja="発熱・咳嗽"), None)
    assert "Fever, cough" in out.raw_text and "発熱" not in out.raw_text, out.raw_text


def test_ed_visit_without_a_localized_field_keeps_the_summary() -> None:
    out = render_ed_triage_note(_ctx("ja"), None)
    assert "Fever, cough" in out.raw_text
