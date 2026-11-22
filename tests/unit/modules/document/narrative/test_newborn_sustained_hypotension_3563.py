"""A newborn's one borderline systolic reading is not called hypotension or a
worsening course (Issue #3563); a sustained low, or a low with another abnormal
vital, is. Adults are judged on a single reading as before."""

from __future__ import annotations

import pytest

from clinosim.modules.document.narrative._progress_exam import (
    course_line,
    current_states,
    period_states,
    progress_exam_findings,
    progress_exam_rules,
)
from clinosim.modules.document.narrative._progress_state import finding_states
from tests.unit.modules.document.narrative.test_progress_exam_course_3235_3247 import _ctx, _v

pytestmark = pytest.mark.unit

_BP = ("systolic_bp", "low")
_OK = {"heart_rate": 140, "respiratory_rate": 45, "spo2": 97.0, "temperature_celsius": 36.8}
_EXAM = {"cardiovascular": {"all": "整、心雑音なし"}}


def _newborn(vitals: list[dict], day: int = 2, lang: str = "ja"):
    ctx = _ctx(vitals, day=day, lang=lang)
    ctx.patient = {"date_of_birth": "2026-05-01"}
    return ctx


def _bp(day: int, hour: int, sbp: float, **over) -> dict:
    return _v(day, hour, systolic_bp=sbp, **{**_OK, **over})


def test_single_borderline_reading_is_not_hypotension() -> None:
    before = [_bp(1, 8, 70)]
    now = [_bp(2, 0, 62), _bp(2, 8, 58)]
    ctx = _newborn(before + now)
    assert "low" not in period_states(ctx, now, before)["systolic_bp"]
    assert "low" not in current_states(ctx, now, before)["systolic_bp"]
    assert finding_states(ctx, now, before)[_BP] == "absent"
    for lang in ("ja", "en"):
        assert course_line(_newborn(before + now, lang=lang), now, before, lang) == ""
    text = progress_exam_findings(ctx, now, _EXAM, "mild", "ja", before)["cardiovascular"]
    assert "血圧低下" not in text


def test_borderline_reading_does_not_say_worsening() -> None:
    before = [_bp(1, 8, 70)]
    now = [_bp(2, 8, 57)]
    for lang, word in (("ja", "増悪"), ("en", "worsen")):
        line = course_line(_newborn(before + now, lang=lang), now, before, lang)
        assert word not in line and "血圧低下" not in line and "hypotension" not in line


def test_two_consecutive_lows_are_hypotension() -> None:
    before = [_bp(1, 8, 70)]
    now = [_bp(2, 0, 57), _bp(2, 8, 57)]
    ctx = _newborn(before + now)
    assert "low" in current_states(ctx, now, before)["systolic_bp"]
    assert finding_states(ctx, now, before)[_BP] == "new"
    assert "血圧低下" in course_line(ctx, now, before, "ja")
    assert "血圧低下" in progress_exam_findings(ctx, now, _EXAM, "mild", "ja", before)["cardiovascular"]


def test_low_run_continuing_from_the_previous_period_counts() -> None:
    before = [_bp(1, 8, 58)]
    now = [_bp(2, 8, 57)]
    ctx = _newborn(before + now)
    assert "low" in current_states(ctx, now, before)["systolic_bp"]
    assert finding_states(ctx, now, before)[_BP] == "persisting"


def test_low_with_another_abnormal_vital_counts() -> None:
    now = [_bp(2, 8, 58, heart_rate=190)]
    ctx = _newborn(now)
    assert "low" in current_states(ctx, now)["systolic_bp"]


def test_low_followed_by_a_normal_reading_does_not_count_for_a_single_low() -> None:
    now = [_bp(2, 0, 58), _bp(2, 8, 70)]
    assert "low" not in period_states(_newborn(now), now)["systolic_bp"]


def test_adult_single_low_reading_still_counts() -> None:
    now = [_v(2, 8, systolic_bp=85, heart_rate=80)]
    ctx = _ctx(now, day=2)
    assert "low" in period_states(ctx, now)["systolic_bp"]
    assert "low" in current_states(ctx, now)["systolic_bp"]


def test_sustained_low_yaml_names_known_vitals() -> None:
    rules = progress_exam_rules()
    assert rules.sustained_low["systolic_bp"].min_readings >= 2
