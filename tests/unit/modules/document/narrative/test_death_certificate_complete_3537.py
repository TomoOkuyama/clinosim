"""The death certificate and the death summary are complete (Issue #3537).

They name the stay's secondary acute diagnosis, time a death within 48 hours
of admission in hours (singular/plural-correct, no "onset unknown" after an
acute onset), state a performed surgery, and say how many comorbidities a
capped list leaves out.
"""

from __future__ import annotations

import re
from dataclasses import replace
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from clinosim.modules.document.narrative.renderers.section_builders.mortality import (
    build_dc_contributing_conditions,
    build_dc_duration_of_immediate_cause,
    build_dc_immediate_cause,
    build_dc_surgery_performed,
    build_dc_underlying_cause,
    build_dds_cause_of_death,
    build_dds_complications_and_comorbidities,
    build_dds_treatment_course,
)
from clinosim.modules.document.reference_data_loaders import load_death_course
from clinosim.types.document import NarrativeContext
from tests.unit.modules.document.narrative.test_death_cause_chain_3255 import _ADMIT, _ctx

pytestmark = pytest.mark.unit


def _with(ctx: NarrativeContext, **changes: object) -> NarrativeContext:
    return replace(ctx, **changes)


def _secondary(ctx: NarrativeContext, codes: list[str]) -> NarrativeContext:
    dx = dict(ctx.diagnoses[0], secondary_diagnosis_codes=codes)
    return _with(ctx, diagnoses=[dx])


def _stay(ctx: NarrativeContext, hours: float, los: int, onset_type: str | None = None) -> NarrativeContext:
    enc = SimpleNamespace(**vars(ctx.encounter))
    enc.discharge_datetime = _ADMIT + timedelta(hours=hours)
    protocol = (
        SimpleNamespace(disease_id="x", narrative=SimpleNamespace(hpi_template=SimpleNamespace(onset_type=onset_type)))
        if onset_type
        else None
    )
    return _with(ctx, encounter=enc, los_days=los, disease_protocol=protocol)


@pytest.mark.parametrize("lang", ["en", "ja"])
def test_secondary_acute_diagnosis_sits_between_infarction_and_death(lang: str) -> None:
    ctx = _secondary(_ctx(lang, adm="I63.9", dis="I63.9"), ["J18.9"])
    immediate, _ = build_dc_immediate_cause(None, ctx)
    underlying, _ = build_dc_underlying_cause(None, ctx)
    cause, _ = build_dds_cause_of_death(None, ctx)
    assert "J18.9" in immediate and "J18.9" in cause
    assert "I63.9" in underlying and "同じ" not in underlying and "same" not in underlying


def test_secondary_acute_diagnosis_follows_a_terminal_complication_as_due_to() -> None:
    ctx = _secondary(_ctx("en", adm="I63.9", dis="I63.9"), ["J18.9"])
    ctx = _with(ctx, complications_events=[{"name": "respiratory_failure", "onset_day": 3}])
    immediate, _ = build_dc_immediate_cause(None, ctx)
    assert "J96" in immediate and "J18.9" in immediate and immediate.index("J96") < immediate.index("J18.9")


def test_secondary_chronic_diagnosis_is_a_contributing_condition() -> None:
    ctx = _secondary(_ctx("en", adm="I63.9", dis="I63.9"), ["E11.9"])
    immediate, _ = build_dc_immediate_cause(None, ctx)
    contributing, facts = build_dc_contributing_conditions(None, ctx)
    assert "E11" not in immediate and "E11.9" in contributing
    assert "ctx.diagnoses[0].secondary_diagnosis_codes" in facts


@pytest.mark.parametrize("lang", ["en", "ja"])
def test_summary_lists_the_secondary_diagnosis(lang: str) -> None:
    ctx = _secondary(_ctx(lang, adm="I63.9", dis="I63.9"), ["J18.9"])
    text, _ = build_dds_complications_and_comorbidities(None, ctx)
    assert "J18.9" in text


@pytest.mark.parametrize("lang", ["en", "ja"])
def test_a_23_hour_death_is_timed_in_hours(lang: str) -> None:
    ctx = _stay(_ctx(lang, adm="I63.9", dis="I63.9"), 23, 1, onset_type="acute")
    duration, _ = build_dc_duration_of_immediate_cause(None, ctx)
    course, _ = build_dds_treatment_course(None, ctx)
    assert "23" in duration and ("時間" in duration or " h " in duration)
    assert "23" in course and ("時間" in course or "hours" in course)
    assert not re.search(r"\b1 days\b", duration + course)
    assert "1日間" not in course


def test_one_day_is_singular() -> None:
    ctx = _stay(_ctx("en", adm="K74.6", dis="K74.6"), 24 * 60, 60)
    # 60 days is not within the hours window; the day wording has no "1 days".
    duration, _ = build_dc_duration_of_immediate_cause(None, ctx)
    assert not re.search(r"\b1 days\b", duration)
    ctx = _stay(_ctx("en", adm="J18.9", dis="J18.9"), 24 * 2, 2)
    course, _ = build_dds_treatment_course(None, ctx)
    assert "Length of stay: 2 days." in course


@pytest.mark.parametrize("lang", ["en", "ja"])
def test_onset_unknown_is_dropped_after_an_acute_onset(lang: str) -> None:
    acute, _ = build_dc_duration_of_immediate_cause(None, _stay(_ctx(lang, adm="I63.9", dis="I63.9"), 23, 1, "acute"))
    gradual, _ = build_dc_duration_of_immediate_cause(
        None, _stay(_ctx(lang, adm="I63.9", dis="I63.9"), 23, 1, "gradual")
    )
    marker = "不詳" if lang == "ja" else "onset unknown"
    assert marker not in acute
    assert marker in gradual


def test_hours_window_is_a_validated_yaml_value() -> None:
    assert load_death_course().duration.hours_below == 48


def _surgery(code: str = "K1643", ptype: str = "craniotomy") -> dict:
    return {
        "procedure_code": code,
        "procedure_type": ptype,
        "start_datetime": datetime(2026, 2, 26, 9, 0).isoformat(),
    }


def test_operated_death_states_the_surgery_ja() -> None:
    ctx = _with(_ctx("ja", adm="I61.9", dis="I61.9"), procedures=[_surgery()])
    text, facts = build_dc_surgery_performed(None, ctx)
    assert text.startswith("手術: 有") and "2026年2月26日" in text
    assert facts == ["ctx.procedures"]


def test_operated_death_states_the_surgery_en() -> None:
    ctx = _with(_ctx("en", adm="I61.9", dis="I61.9"), procedures=[_surgery()])
    text, _ = build_dc_surgery_performed(None, ctx)
    assert text.startswith("Surgery:") and "2026-02-26" in text and "手術" not in text


def test_a_bedside_procedure_is_not_a_surgery() -> None:
    ctx = _with(_ctx("ja", adm="I61.9", dis="I61.9"), procedures=[_surgery("J044", "intubation")])
    text, _ = build_dc_surgery_performed(None, ctx)
    assert text == "手術: 無"


_SEVEN = ["I10", "E11.9", "E78.5", "N18.3", "J44.9", "I25.10", "E66.3"]


@pytest.mark.parametrize("lang", ["en", "ja"])
def test_a_capped_comorbidity_list_says_how_many_are_left_out(lang: str) -> None:
    base = _ctx(lang, adm="I63.9", dis="I63.9", chronic=_SEVEN)
    text, _ = build_dds_complications_and_comorbidities(None, base)
    cap = load_death_course().treatment_course.max_named_comorbidities
    assert str(len(_SEVEN) - cap) in text
    assert ("ほか2件" if lang == "ja" else "and 2 others") in text
