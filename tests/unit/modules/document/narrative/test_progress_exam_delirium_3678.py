"""While a delirium complication is active the JP exam does not state 意識清明
(Issue #3678): delirium is a disturbance of attention and awareness, so the
clear-consciousness clause gives way to a delirium finding even when every
recorded AVPU is Alert."""

from __future__ import annotations

import pytest

from clinosim.modules.document.narrative._progress_exam import delirium_active
from clinosim.modules.document.narrative.renderers._composers import apply_cc_pe_consistency
from tests.unit.modules.document.narrative.test_progress_exam_course_3235_3247 import _ctx, _v

pytestmark = pytest.mark.unit

_TEXT = "一般状態: 意識清明、全身状態良好。循環器: 整"


def _delirium(**extra) -> dict:
    return {
        "name": "delirium",
        "onset_day": 2,
        "onset_datetime": "2026-05-03T12:00:00",
        "source": "daily_loop",
        **extra,
    }


def _note(day: int, events: list[dict], *, lang: str = "ja", level: str = "A") -> tuple[str, list[str]]:
    vitals = [_v(d, 8, consciousness_level=level) for d in range(day + 1)]
    ctx = _ctx(vitals, day=day, lang=lang, events=events)
    return apply_cc_pe_consistency(_TEXT, ctx, use_chief_complaint=False)


def test_active_delirium_replaces_clear_consciousness() -> None:
    text, facts = _note(3, [_delirium()])
    assert "意識清明" not in text and "見当識障害" in text
    assert "循環器: 整" in text
    assert facts == ["ctx.complications_events:pe_consciousness_delirium"]


def test_before_onset_the_clause_is_unchanged() -> None:
    text, facts = _note(1, [_delirium()])
    assert "意識清明" in text and facts == []


def test_after_resolution_the_clause_is_unchanged() -> None:
    text, _ = _note(4, [_delirium(resolution_day=4)])
    assert "意識清明" in text
    text, _ = _note(3, [_delirium(resolution_day=4)])
    assert "意識清明" not in text


def test_no_delirium_is_unchanged() -> None:
    text, facts = _note(3, [{"name": "pneumonia", "onset_day": 1, "onset_datetime": None, "source": "daily_loop"}])
    assert text == _TEXT and facts == []


def test_lowered_avpu_keeps_the_avpu_phrase() -> None:
    text, facts = _note(3, [_delirium()], level="V")
    assert "意識清明" not in text
    assert facts == ["ctx.vitals.consciousness_level:pe_consciousness"]


def test_choice_is_deterministic() -> None:
    assert _note(3, [_delirium()])[0] == _note(3, [_delirium()])[0]


def test_icu_and_postoperative_names_count() -> None:
    for name in ("icu_delirium", "postoperative_delirium"):
        ctx = _ctx([_v(3, 8, consciousness_level="A")], day=3, events=[_delirium(name=name)])
        assert delirium_active(ctx)


def test_note_authored_before_onset_time_is_not_delirious() -> None:
    from datetime import datetime

    ctx = _ctx([_v(2, 8, consciousness_level="A")], day=2, events=[_delirium(onset_day=2)])
    ctx.authored_datetime = datetime(2026, 5, 3, 9, 0)
    assert not delirium_active(ctx)
