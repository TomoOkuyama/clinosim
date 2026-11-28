"""Issue #3964: a vital that stays near its threshold is not reported as a new
finding one day and a resolved one the next.

A finding is entered at the entry limit of ``progress_exam.yaml`` ``limits`` and
left only beyond the vital's ``exit_margin`` from it (a modelling choice, kept in
the YAML): a value between the two is borderline, so a heart rate of 98 to 104
over several days is neither "new tachycardia" nor "tachycardia resolved"."""

from __future__ import annotations

import pytest

from clinosim.modules.document.narrative import _progress_exam
from clinosim.modules.document.narrative._progress_exam import course_line, progress_exam_rules
from clinosim.modules.document.narrative._progress_state import finding_states
from tests.unit.modules.document.narrative.test_progress_exam_course_3235_3247 import _ctx, _v

pytestmark = pytest.mark.unit

_HR = ("heart_rate", "high")
_NEW_OR_RESOLVED = ("new", "resolved", "新たに", "消失")


def _day(day: int, **fields) -> list[dict]:
    return [_v(day, 8, **fields)]


def _transition(vital: str, before: float, now: float, lang: str = "en", extra_now: float | None = None):
    prev = _day(1, **{vital: before})
    cur = _day(2, **{vital: now})
    if extra_now is not None:
        cur = [_v(2, 2, **{vital: extra_now}), *cur]
    ctx = _ctx(prev + cur, day=2, lang=lang)
    return finding_states(ctx, cur, prev), course_line(ctx, cur, prev, lang)


@pytest.mark.parametrize("lang", ["en", "ja"])
def test_a_heart_rate_around_the_threshold_is_never_new_or_resolved(lang: str) -> None:
    series = [99, 103, 100, 104, 98, 102, 100, 97]
    for before, now in zip(series, series[1:], strict=False):
        states, line = _transition("heart_rate", before, now, lang)
        assert states[_HR] in {"persisting", "borderline", "absent"}, (before, now, states[_HR])
        assert not any(word in line for word in _NEW_OR_RESOLVED), (before, now, line)


def test_a_borderline_reading_after_tachycardia_states_no_course() -> None:
    states, line = _transition("heart_rate", 103, 100)
    assert states[_HR] == "borderline"
    assert line == ""


@pytest.mark.parametrize(
    ("vital", "before", "now", "name"),
    [
        ("heart_rate", 90, 115, "tachycardia"),
        ("respiratory_rate", 16, 26, "tachypnea"),
        ("temperature_celsius", 36.8, 38.6, "fever"),
        ("spo2", 97, 90, "low SpO2"),
    ],
)
def test_a_real_change_is_still_new(vital: str, before: float, now: float, name: str) -> None:
    states, line = _transition(vital, before, now)
    assert states[(vital, "low" if vital == "spo2" else "high")] == "new"
    assert f"worsening compared with the previous day (new {name})" in line


@pytest.mark.parametrize(
    ("vital", "before", "now", "name"),
    [
        ("heart_rate", 115, 88, "tachycardia"),
        ("respiratory_rate", 26, 16, "tachypnea"),
        ("temperature_celsius", 38.6, 36.8, "fever"),
        ("spo2", 90, 97, "low SpO2"),
    ],
)
def test_a_real_recovery_is_still_resolved(vital: str, before: float, now: float, name: str) -> None:
    states, line = _transition(vital, before, now, extra_now=now)
    assert states[(vital, "low" if vital == "spo2" else "high")] == "resolved"
    assert f"{name} resolved" in line


@pytest.mark.parametrize(
    ("vital", "series"),
    [
        ("respiratory_rate", [19, 21, 20, 21, 19, 21]),
        ("temperature_celsius", [37.9, 38.0, 37.8, 38.1, 37.9]),
        ("spo2", [94, 93, 94, 95, 93, 94]),
    ],
)
def test_the_other_vitals_share_the_rule(vital: str, series: list[float]) -> None:
    for before, now in zip(series, series[1:], strict=False):
        _states, line = _transition(vital, before, now)
        assert not any(word in line for word in _NEW_OR_RESOLVED), (vital, before, now, line)


def test_the_exit_margins_are_yaml_data() -> None:
    limits = progress_exam_rules().limits
    for vital in ("heart_rate", "respiratory_rate", "temperature_celsius", "spo2"):
        assert (limits[vital].exit_margin or 0) > 0, vital
    assert limits["pain_score"].exit_margin is None


def test_without_a_margin_the_flat_heart_rate_flips(monkeypatch: pytest.MonkeyPatch) -> None:
    """The margin is what prevents the flip: with none, 100 then 103 is a new tachycardia."""
    rules = progress_exam_rules()
    limits = {k: v.model_copy(update={"exit_margin": None}) for k, v in rules.limits.items()}
    monkeypatch.setattr(_progress_exam, "progress_exam_rules", lambda: rules.model_copy(update={"limits": limits}))
    states, _line = _transition("heart_rate", 100, 103)
    assert states[_HR] == "new"
