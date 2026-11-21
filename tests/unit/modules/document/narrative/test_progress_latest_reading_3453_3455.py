"""Hypothermia, the consciousness line and the vital course claims of a
progress note follow the latest reading and a meaningful change (Issues #3453,
#3455)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from clinosim.modules.document.narrative._narrative_interpretation_thresholds import (
    progress_vitals_rules,
)
from clinosim.modules.document.narrative._progress_exam import course_line, progress_exam_rules
from clinosim.modules.document.narrative.renderers._composers import compose_progress_subjective_from_state
from tests.unit.modules.document.narrative.test_progress_exam_course_3235_3247 import _ctx, _v

pytestmark = pytest.mark.unit


def _subj(vitals: list[dict], lang: str, day: int = 2) -> str:
    return compose_progress_subjective_from_state(_ctx(vitals, day=day, lang=lang))


def test_hypothermia_threshold_is_the_core_definition() -> None:
    assert progress_vitals_rules().trend.hypothermia_below_c == 35.0


@pytest.mark.parametrize("lang,word", [("ja", "低体温"), ("en", "ypothermia")])
def test_mild_low_temperature_is_not_hypothermia(lang: str, word: str) -> None:
    assert word not in _subj([_v(1, 9, temperature_celsius=36.5), _v(2, 8, temperature_celsius=35.9)], lang)


def test_hypothermia_is_judged_on_the_latest_reading() -> None:
    vitals = [
        _v(1, 9, temperature_celsius=36.5),
        _v(2, 2, temperature_celsius=34.6),
        _v(2, 8, temperature_celsius=34.8),
    ]
    en, ja = _subj(vitals, "en"), _subj(vitals, "ja")
    assert "Hypothermia 34.8" in en and "34.6" in en
    assert "低体温 34.8" in ja and "34.6" in ja


@pytest.mark.parametrize("lang,word", [("ja", "低体温 36"), ("en", "Hypothermia 36")])
def test_recovered_low_temperature_is_time_qualified(lang: str, word: str) -> None:
    vitals = [
        _v(1, 9, temperature_celsius=36.5),
        _v(2, 2, temperature_celsius=34.6),
        _v(2, 8, temperature_celsius=36.4),
    ]
    text = _subj(vitals, lang)
    assert "34.6" in text and "36.4" in text and word not in text


def test_consciousness_states_the_latest_level_not_the_period_worst() -> None:
    vitals = [_v(1, 9, consciousness_level="A"), _v(2, 2, consciousness_level="U"), _v(2, 8, consciousness_level="A")]
    en, ja = _subj(vitals, "en"), _subj(vitals, "ja")
    assert "remains decreased" not in en and "AVPU U" in en and "now alert" in en
    assert "低下持続" not in ja and "AVPU U" in ja and "現在は清明" in ja


def test_consciousness_improved_since_yesterday_is_not_called_persistent() -> None:
    vitals = [_v(1, 9, consciousness_level="U"), _v(2, 2, consciousness_level="U"), _v(2, 8, consciousness_level="A")]
    assert "remains decreased" not in _subj(vitals, "en") and "低下持続" not in _subj(vitals, "ja")


def test_consciousness_still_reduced_names_latest_and_peak() -> None:
    vitals = [_v(1, 9, consciousness_level="V"), _v(2, 2, consciousness_level="U"), _v(2, 8, consciousness_level="V")]
    en = _subj(vitals, "en")
    assert "remains decreased (AVPU V)" in en and "worst AVPU U" in en


@pytest.mark.parametrize("lang", ["ja", "en"])
def test_never_resolved_while_latest_avpu_is_below_alert(lang: str) -> None:
    before = [_v(1, 8, consciousness_level="U")]
    now = [_v(2, 2, consciousness_level="A"), _v(2, 8, consciousness_level="V")]
    ctx = _ctx(before + now, day=2, lang=lang)
    line = course_line(ctx, now, before, lang)
    assert "消失" not in line and "resolved" not in line


def test_pain_self_report_follows_the_latest_avpu() -> None:
    vitals = [_v(1, 9, consciousness_level="U"), _v(2, 8, consciousness_level="A", pain_score=5)]
    ctx = _ctx(vitals, day=2, lang="ja")
    ctx.disease_protocol = SimpleNamespace(disease_id="hip_fracture")  # a disease with a pain site (Issue #3454)
    text = compose_progress_subjective_from_state(ctx)
    assert "股関節部痛" in text and "自己申告" not in text


def test_course_items_carry_a_meaningful_change_per_vital() -> None:
    numeric = [i for i in progress_exam_rules().course_items if i.vital not in ("consciousness", "on_oxygen")]
    assert numeric and all(i.min_change is not None and i.min_change > 0 for i in numeric)


@pytest.mark.parametrize("lang,word", [("ja", "改善傾向"), ("en", "improving")])
def test_persisting_tachypnea_that_fell_meaningfully_is_improving(lang: str, word: str) -> None:
    before = [_v(1, 8, respiratory_rate=26)]
    now = [_v(2, 8, respiratory_rate=21)]
    line = course_line(_ctx(before + now, day=2, lang=lang), now, before, lang)
    assert (
        word in line and "26" in line and "21" in line and "改善に乏しい" not in line and "no improvement" not in line
    )


def test_persisting_without_meaningful_change_stays_persisting() -> None:
    before = [_v(1, 8, respiratory_rate=22)]
    now = [_v(2, 8, respiratory_rate=21)]
    assert "改善に乏しい" in course_line(_ctx(before + now, day=2, lang="ja"), now, before, "ja")


def test_persisting_that_rose_meaningfully_is_worsening() -> None:
    before = [_v(1, 8, respiratory_rate=22)]
    now = [_v(2, 8, respiratory_rate=28)]
    line = course_line(_ctx(before + now, day=2, lang="en"), now, before, "en")
    assert "worsening" in line and "22" in line and "28" in line


def test_low_state_improvement_goes_the_other_way() -> None:
    before = [_v(1, 8, spo2=88.0)]
    now = [_v(2, 8, spo2=92.0)]
    line = course_line(_ctx(before + now, day=2, lang="en"), now, before, "en")
    assert "improving" in line
