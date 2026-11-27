"""Issue #3914: a progress note states a drug switch only from the hospital day
it happens (``stopped_on_day``); an earlier note says nothing about it."""

from __future__ import annotations

import pytest

from clinosim.modules.document.narrative._safety_skips import progress_note_safety_skips
from clinosim.modules.document.narrative._template_helpers import _render_safety_skips_line


def _switch(drug: str, day: int | None) -> dict:
    return {
        "considered": drug,
        "considered_ja": drug,
        "avoided_due_to": "treatment plan change",
        "avoided_due_to_ja": "治療計画変更",
        "substituted_with": None,
        "event_type": "switch",
        "rule_id": "treatment-modification-switch",
        "stopped_on_day": day,
    }


@pytest.mark.parametrize("lang", ["en", "ja"])
def test_switch_absent_before_its_day_present_from_it(lang: str) -> None:
    skips = [_switch("Vancomycin", 9)]
    for hospital_day in (1, 3, 8):
        assert progress_note_safety_skips(skips, hospital_day=hospital_day) == []
        assert _render_safety_skips_line(progress_note_safety_skips(skips, hospital_day=hospital_day), lang) == ""
    for hospital_day in (9, 10, 21):
        kept = progress_note_safety_skips(skips, hospital_day=hospital_day)
        assert len(kept) == 1
        assert "9" in _render_safety_skips_line(kept, lang)


def test_switch_without_a_day_is_kept_and_hospital_day_is_optional() -> None:
    assert len(progress_note_safety_skips([_switch("Vancomycin", None)], hospital_day=2)) == 1
    assert len(progress_note_safety_skips([_switch("Vancomycin", 9)])) == 1


def test_llm_prompt_of_a_progress_note_omits_a_later_switch() -> None:
    from clinosim.modules.document.narrative.replacement_strategy import _build_extra_context
    from tests.unit.modules.document.narrative.test_safety_skip_event_types import _make_ctx, _Spec

    spec = _Spec("progress_note")
    early = _make_ctx([_switch("Vancomycin", 9)], doc_type="progress_note")
    early.day_index = 2
    late = _make_ctx([_switch("Vancomycin", 9)], doc_type="progress_note")
    late.day_index = 8
    assert "considered_but_not_prescribed" not in _build_extra_context(early, spec)
    assert "Vancomycin" in _build_extra_context(late, spec)["considered_but_not_prescribed"]


@pytest.mark.parametrize("doc_type", ["admission_hp", "admission_nursing_assessment", "admission_care_plan", "ed_note"])
def test_llm_prompt_of_an_admission_document_omits_a_later_switch_3943(doc_type: str) -> None:
    """Issue #3943: the prompt input of a document written at admission carries no
    switch dated on a later hospital day."""
    from clinosim.modules.document.narrative.replacement_strategy import _build_extra_context
    from tests.unit.modules.document.narrative.test_safety_skip_event_types import _make_ctx, _Spec

    ctx = _make_ctx([_switch("Piperacillin/Tazobactam", 15)])
    assert "considered_but_not_prescribed" not in _build_extra_context(ctx, _Spec(doc_type))


@pytest.mark.parametrize("doc_type", ["discharge_summary", "death_discharge_summary", "nursing_discharge_summary"])
def test_llm_prompt_of_a_whole_stay_document_keeps_the_switch_3943(doc_type: str) -> None:
    from clinosim.modules.document.narrative.replacement_strategy import _build_extra_context
    from tests.unit.modules.document.narrative.test_safety_skip_event_types import _make_ctx, _Spec

    ctx = _make_ctx([_switch("Piperacillin/Tazobactam", 15)])
    assert "Piperacillin" in _build_extra_context(ctx, _Spec(doc_type))["considered_but_not_prescribed"]
