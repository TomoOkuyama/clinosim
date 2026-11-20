"""Progress-note statements about the patient's vitals follow the latest
reading the Objective prints; an earlier peak is stated time-qualified, and a
COPD patient's SpO2 target floor is 88 % (Issue #3401)."""

from __future__ import annotations

import pytest

from clinosim.modules.document.narrative._progress_exam import (
    course_line,
    current_states,
    period_states,
    progress_exam_findings,
)
from clinosim.modules.document.narrative.renderers._composers import compose_progress_subjective_from_state
from tests.unit.modules.document.narrative.test_progress_exam_course_3235_3247 import _ctx, _v

pytestmark = pytest.mark.unit


def _subj(vitals: list[dict], *, lang: str, day: int = 2, copd: bool = False) -> str:
    ctx = _ctx(vitals, day=day, lang=lang)
    if copd:
        ctx.patient = {"date_of_birth": "1950-01-01", "chronic_conditions": [{"code": "J44.9"}]}
    return compose_progress_subjective_from_state(ctx)


_OVERNIGHT_FEVER = [
    _v(1, 9, temperature_celsius=37.0),
    _v(2, 2, temperature_celsius=38.1),
    _v(2, 8, temperature_celsius=36.7),
]


def test_overnight_fever_is_time_qualified_not_new_onset() -> None:
    ja = _subj(_OVERNIGHT_FEVER, lang="ja")
    en = _subj(_OVERNIGHT_FEVER, lang="en")
    assert "38.1" in ja and "現在 36.7" in ja and "出現" not in ja and "持続" not in ja
    assert "38.1" in en and "now 36.7" in en and "New-onset" not in en and "Persistent" not in en


def test_persistent_fever_states_the_latest_value_with_the_peak() -> None:
    vitals = [
        _v(1, 9, temperature_celsius=38.5),
        _v(2, 2, temperature_celsius=39.3),
        _v(2, 8, temperature_celsius=38.2),
    ]
    en = _subj(vitals, lang="en")
    assert "Persistent fever 38.2°C" in en and "peak 39.3°C" in en
    ja = _subj(vitals, lang="ja")
    assert "発熱 38.2°C" in ja and "最高 39.3°C" in ja


def test_transient_desaturation_is_time_qualified() -> None:
    vitals = [_v(1, 9, spo2=96.0), _v(2, 2, spo2=90.0), _v(2, 8, spo2=96.0)]
    en = _subj(vitals, lang="en")
    assert "fell to 90%" in en and "now 96%" in en and "desaturation trend" not in en
    ja = _subj(vitals, lang="ja")
    assert "現在 96%" in ja and "低下傾向" not in ja


def test_copd_patient_at_90_percent_is_not_desaturating() -> None:
    vitals = [_v(1, 9, spo2=91.5), _v(2, 8, spo2=90.0)]
    assert "desaturation" in _subj(vitals, lang="en")
    assert "desaturation" not in _subj(vitals, lang="en", copd=True)
    ctx = _ctx(vitals, lang="en")
    ctx.patient = {"date_of_birth": "1950-01-01", "chronic_conditions": [{"code": "J44.1"}]}
    assert period_states(ctx, vitals)["spo2"] == {"normal"}
    assert period_states(_ctx(vitals, lang="en"), vitals)["spo2"] == {"low"}


def test_current_states_use_the_latest_reading() -> None:
    vitals = [_v(2, 2, respiratory_rate=24, spo2=92.0), _v(2, 8, respiratory_rate=18, spo2=95.0)]
    ctx = _ctx(vitals, day=2)
    assert period_states(ctx, vitals)["respiratory_rate"] == {"high"}
    assert current_states(ctx, vitals)["respiratory_rate"] == {"normal"}
    assert current_states(ctx, vitals)["spo2"] == {"normal"}


@pytest.mark.parametrize("lang", ["ja", "en"])
def test_course_line_does_not_assert_a_peak_the_latest_reading_lacks(lang: str) -> None:
    now = [_v(2, 2, respiratory_rate=24, spo2=92.0), _v(2, 8, respiratory_rate=18, spo2=95.0)]
    before = [_v(1, 8, respiratory_rate=18, spo2=96.0)]
    ctx = _ctx(before + now, day=2, lang=lang)
    assert course_line(ctx, now, before, lang) == ""


def test_course_line_is_scoped_to_vitals() -> None:
    now = [_v(2, 8, temperature_celsius=36.8)]
    before = [_v(1, 8, temperature_celsius=38.6)]
    assert "バイタル" in course_line(_ctx(before + now, day=2, lang="ja"), now, before, "ja")
    assert "Vital signs" in course_line(_ctx(before + now, day=2, lang="en"), now, before, "en")


def test_exam_adds_no_finding_the_latest_reading_does_not_show() -> None:
    vitals = [_v(2, 2, spo2=92.0, respiratory_rate=24), _v(2, 8, spo2=96.0, respiratory_rate=16)]
    ctx = _ctx(vitals, day=2)
    exam = {"respiratory": {"all": "呼吸音清明"}}
    text = progress_exam_findings(ctx, vitals, exam, "moderate", "ja")["respiratory"]
    assert "SpO2 低下" not in text and "頻呼吸" not in text
