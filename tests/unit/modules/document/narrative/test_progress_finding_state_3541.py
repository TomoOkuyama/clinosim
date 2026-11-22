"""A progress note states each vital finding in one state (Issue #3541): new,
persisting, improving or resolved, never two of them, and "resolved" only for a
finding absent over the sustained window."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from clinosim.modules.document.narrative._progress_exam import course_line, progress_exam_rules
from clinosim.modules.document.narrative._progress_state import finding_states
from clinosim.modules.document.narrative._vitals_line import latest_vitals_set
from clinosim.modules.document.narrative.renderers._composers import compose_progress_subjective_from_state
from tests.unit.modules.document.narrative.test_progress_exam_course_3235_3247 import _ctx, _v

pytestmark = pytest.mark.unit

_FEVER = ("temperature_celsius", "high")
_AVPU = ("consciousness", "high")


def test_latest_vitals_set_skips_a_blank_avpu() -> None:
    merged = latest_vitals_set([_v(2, 2, consciousness_level="U"), _v(2, 8, consciousness_level="", heart_rate=80)])
    assert merged["consciousness_level"] == "U"


@pytest.mark.parametrize("lang", ["ja", "en"])
def test_blank_monitor_avpu_does_not_resolve_consciousness(lang: str) -> None:
    before = [_v(1, 8, consciousness_level="U")]
    now = [_v(2, 2, consciousness_level="U"), _v(2, 8, consciousness_level="", heart_rate=80)]
    ctx = _ctx(before + now, day=2, lang=lang)
    line = course_line(ctx, now, before, lang)
    assert "消失" not in line and "resolved" not in line
    subj = compose_progress_subjective_from_state(ctx)
    assert ("低下持続" in subj) or ("remains decreased" in subj)
    assert "new decrease" not in subj.lower() and "低下あり" not in subj


def test_state_is_one_per_finding() -> None:
    before = [_v(1, 8, consciousness_level="U", temperature_celsius=38.6)]
    now = [_v(2, 2, consciousness_level="U", temperature_celsius=38.2), _v(2, 8, consciousness_level="U")]
    states = finding_states(_ctx(before + now, day=2), now, before)
    assert states[_AVPU] == "persisting" and states[_FEVER] == "persisting"


def test_single_normal_reading_is_not_resolved() -> None:
    before = [_v(1, 8, temperature_celsius=38.6)]
    now = [_v(2, 8, temperature_celsius=37.1)]
    ctx = _ctx(before + now, day=2, lang="en")
    assert finding_states(ctx, now, before)[_FEVER] == "improving"
    assert "resolved" not in course_line(ctx, now, before, "en")


def test_sustained_normal_readings_resolve() -> None:
    before = [_v(1, 8, temperature_celsius=38.6)]
    now = [_v(2, 2, temperature_celsius=37.1), _v(2, 8, temperature_celsius=37.0)]
    ctx = _ctx(before + now, day=2, lang="en")
    assert finding_states(ctx, now, before)[_FEVER] == "resolved"
    assert "fever resolved" in course_line(ctx, now, before, "en")


def test_fever_inside_the_window_prevents_resolved() -> None:
    before = [_v(1, 8, temperature_celsius=38.6)]
    now = [_v(2, 1, temperature_celsius=38.1), _v(2, 7, temperature_celsius=37.1), _v(2, 8, temperature_celsius=37.0)]
    ctx = _ctx(before + now, day=2, lang="en")
    assert finding_states(ctx, now, before)[_FEVER] == "improving"
    assert "resolved" not in course_line(ctx, now, before, "en")


@pytest.mark.parametrize("lang", ["ja", "en"])
def test_subjective_and_assessment_agree_on_new_vs_persisting_fever(lang: str) -> None:
    # the previous period peaked at 38.5 but ended at 37.0: the fever is not new
    before = [_v(1, 4, temperature_celsius=38.5), _v(1, 9, temperature_celsius=37.0)]
    now = [_v(2, 8, temperature_celsius=38.0)]
    ctx = _ctx(before + now, day=2, lang=lang)
    assert finding_states(ctx, now, before)[_FEVER] == "persisting"
    subj = compose_progress_subjective_from_state(ctx)
    assert "New-onset" not in subj and "出現" not in subj
    assert "新たに" not in course_line(ctx, now, before, lang) and "new fever" not in course_line(
        ctx, now, before, lang
    )


@pytest.mark.parametrize("lang", ["ja", "en"])
def test_new_fever_is_new_in_both(lang: str) -> None:
    before = [_v(1, 4, temperature_celsius=36.9), _v(1, 9, temperature_celsius=37.0)]
    now = [_v(2, 8, temperature_celsius=38.4)]
    ctx = _ctx(before + now, day=2, lang=lang)
    assert finding_states(ctx, now, before)[_FEVER] == "new"
    subj = compose_progress_subjective_from_state(ctx)
    assert ("出現" in subj) or ("New-onset" in subj)
    assert ("新たに" in course_line(ctx, now, before, lang)) or ("new fever" in course_line(ctx, now, before, lang))


def test_course_state_window_is_in_yaml() -> None:
    rules = progress_exam_rules().course_state
    assert rules.resolved_window_hours > 0 and rules.resolved_min_readings >= 2


def test_subjective_pain_is_the_latest_charted_score() -> None:
    def v(day: int, hour: int, pain: int) -> dict:
        return {"timestamp": datetime(2026, 5, 1 + day, hour, 0), "pain_score": pain}

    ctx = SimpleNamespace(
        target_lang="en",
        vitals=[v(0, 10, 6), v(1, 6, 7), v(1, 15, 5)],
        day_index=1,
        los_days=5,
        encounter={"encounter_id": "E1", "admission_datetime": datetime(2026, 5, 1, 10, 0)},
        disease_protocol=SimpleNamespace(disease_id="hip_fracture"),
        clinical_course_archetype="smooth_recovery",
    )
    text = compose_progress_subjective_from_state(ctx)
    assert "5" in text and "7" not in text
