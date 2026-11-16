"""Nursing documents use only what was known when they were written.

Issue #3236: the admission nursing assessment and the shift notes print the
ADL / risk assessment in force at their authored time, not the last one of
the stay. Issue #3239: each shift note reports the vital signs of its own
shift window. Issue #3240: no nursing note states the final length of stay,
and an at-admission LOS estimate never falls back to the realized LOS.
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from clinosim.modules.document.narrative._as_of import in_force_at
from clinosim.modules.document.narrative._vitals_line import latest_vitals_set, vitals_in_window
from clinosim.modules.document.narrative.renderers.nursing_shift_note import render_nursing_shift_note
from clinosim.modules.document.narrative.renderers.section_builders.care_plans import (
    build_acp_estimated_los,
    build_ncp_nutrition_assessment,
    build_rp_discharge_estimate,
)
from clinosim.modules.document.narrative.renderers.section_builders.nursing import (
    build_adl_assessment,
    build_care_plan,
    build_discharge_readiness,
    build_nursing_diagnosis,
    build_risk_assessments,
)
from clinosim.modules.document.narrative.template_generator import TemplateNarrativeGenerator

pytestmark = pytest.mark.unit

_ADM = "2026-08-31T09:54:00"
_ADLS = [
    {"date": "2026-08-31", "barthel_score": 40, "feeding": 5, "bathing": 0, "mobility": 5, "toilet_use": 5},
    {"date": "2026-09-07", "barthel_score": 80, "feeding": 10, "bathing": 5, "mobility": 10, "toilet_use": 5},
    {"date": "2026-09-14", "barthel_score": 100, "feeding": 10, "bathing": 5, "mobility": 15, "toilet_use": 10},
]
_RISKS = [
    {"date": "2026-08-31", "braden_total": 12, "morse_total": 60, "fall_risk_level": "high"},
    {"date": "2026-09-14", "braden_total": 23, "morse_total": 15, "fall_risk_level": "low"},
]


def _ctx(authored: datetime | None, lang: str = "ja", **kw) -> SimpleNamespace:
    base = {
        "target_lang": lang,
        "locale": "jp" if lang == "ja" else "us",
        "authored_datetime": authored,
        "day_index": 0,
        "los_days": 21,
        "shift": "",
        "encounter": {"admission_datetime": _ADM},
        "roster_map": {},
        "vitals": [],
        "medications": [],
        "adl_assessments": list(_ADLS),
        "nursing_risk_assessments": list(_RISKS),
        "patient": {"bmi": 22.0, "chronic_conditions": []},
        "disease_protocol": None,
    }
    base.update(kw)
    return SimpleNamespace(**base)


# ── #3236: the assessment in force at the authored time ──────────────────


def test_in_force_at_picks_the_latest_on_or_before_the_time() -> None:
    assert in_force_at(_ADLS, datetime(2026, 8, 31, 9, 54))["barthel_score"] == 40
    assert in_force_at(_ADLS, datetime(2026, 9, 7, 0, 0))["barthel_score"] == 80
    assert in_force_at(_ADLS, datetime(2026, 9, 21, 13, 0))["barthel_score"] == 100


def test_in_force_at_before_the_first_record_is_the_first_record() -> None:
    assert in_force_at(_ADLS, datetime(2026, 8, 30, 23, 0))["barthel_score"] == 40


def test_in_force_at_without_a_time_is_the_last_record_and_empty_is_none() -> None:
    assert in_force_at(_ADLS, None)["barthel_score"] == 100
    assert in_force_at([], datetime(2026, 9, 1)) is None


def test_admission_assessment_prints_the_admission_barthel() -> None:
    text, _ = build_adl_assessment(None, _ctx(datetime(2026, 8, 31, 9, 54)))
    assert "40/100" in text
    assert "100/100" not in text


def test_admission_assessment_prints_the_admission_risks() -> None:
    text, _ = build_risk_assessments(None, _ctx(datetime(2026, 8, 31, 9, 54)))
    assert "Braden 12" in text and "Morse 60" in text
    assert "Braden 23" not in text


def test_admission_nursing_diagnosis_and_care_plan_follow_the_admission_risk() -> None:
    ctx = _ctx(datetime(2026, 8, 31, 9, 54))
    dx, _ = build_nursing_diagnosis(None, ctx)
    plan, _ = build_care_plan(None, ctx)
    assert "転倒" in dx and "褥瘡" in dx
    assert "転倒" in plan


def test_discharge_summary_keeps_the_last_assessment() -> None:
    text, _ = build_discharge_readiness(None, _ctx(datetime(2026, 9, 21, 13, 54)))
    assert "100" in text
    assert "Braden 23" in text


def test_nutrition_plan_reads_the_adl_at_its_time() -> None:
    early, _ = build_ncp_nutrition_assessment(None, _ctx(datetime(2026, 8, 31, 9, 54)))
    late, _ = build_ncp_nutrition_assessment(None, _ctx(datetime(2026, 9, 21, 9, 54)))
    assert "摂食動作に介助必要" in early
    assert early != late


def _shift_note(day: int, shift: str, authored: datetime, lang: str = "ja", **kw) -> str:
    ctx = _ctx(authored, lang=lang, day_index=day, shift=shift, **kw)
    return render_nursing_shift_note(ctx, None).raw_text


def test_shift_note_before_reassessment_prints_the_earlier_risk() -> None:
    early = _shift_note(1, "night", datetime(2026, 9, 1, 0, 0))
    late = _shift_note(14, "night", datetime(2026, 9, 14, 0, 0))
    assert "転倒リスク 高リスク" in early
    assert "転倒リスク" not in late


# ── #3239: each shift reports its own vital signs ─────────────────────────


def _vs(ts: str, hr: int, **kw) -> dict:
    row = {"timestamp": ts, "heart_rate": hr, "systolic_bp": 120, "diastolic_bp": 70, "spo2": 98.0}
    row.update(kw)
    return row


_DAY1 = [
    _vs("2026-09-01T00:02:00", 83),
    _vs("2026-09-01T11:46:00", 87),
    _vs("2026-09-01T18:01:00", 90),
]


def test_each_shift_prints_its_own_reading() -> None:
    night = _shift_note(1, "night", datetime(2026, 9, 1, 0, 0), lang="en", vitals=_DAY1)
    day = _shift_note(1, "day", datetime(2026, 9, 1, 8, 0), lang="en", vitals=_DAY1)
    evening = _shift_note(1, "evening", datetime(2026, 9, 1, 16, 0), lang="en", vitals=_DAY1)
    assert "HR 83" in night and "HR 87" not in night
    assert "HR 87" in day and "HR 83" not in day
    assert "HR 90" in evening and "HR 87" not in evening


def test_a_shift_without_readings_does_not_reuse_another_shift() -> None:
    vitals = [_vs("2026-09-01T00:02:00", 83)]
    day = _shift_note(1, "day", datetime(2026, 9, 1, 8, 0), lang="en", vitals=vitals)
    assert "HR 83" not in day
    assert "no vital record" in day


def test_the_latest_value_of_each_vital_in_the_shift_is_reported() -> None:
    rows = [
        _vs("2026-09-01T09:00:00", 80, temperature_celsius=37.0),
        {"timestamp": "2026-09-01T12:00:00", "heart_rate": 101},
        {"timestamp": "2026-09-01T14:00:00", "temperature_celsius": 38.4},
    ]
    merged = latest_vitals_set(rows)
    assert merged["heart_rate"] == 101
    assert merged["temperature_celsius"] == 38.4
    assert merged["systolic_bp"] == 120


def test_an_earlier_unstable_reading_in_the_shift_is_documented() -> None:
    rows = [
        _vs("2026-09-01T17:10:00", 136, systolic_bp=84, diastolic_bp=55, news2_score=8),
        _vs("2026-09-01T22:00:00", 92, news2_score=1),
    ]
    text = _shift_note(1, "evening", datetime(2026, 9, 1, 16, 0), lang="en", vitals=rows)
    assert "HR 92" in text
    assert "17:10" in text and "HR 136" in text


def test_an_earlier_reading_no_worse_than_the_current_values_is_not_repeated() -> None:
    """A partial latest reading has a low NEWS2 of its own; the comparison is
    with the NEWS2 of the values the status line shows."""
    rows = [
        _vs("2026-09-01T17:10:00", 120, systolic_bp=95, diastolic_bp=60, temperature_celsius=39.2, news2_score=6),
        {"timestamp": "2026-09-01T22:00:00", "heart_rate": 121, "news2_score": 2},
    ]
    text = _shift_note(1, "evening", datetime(2026, 9, 1, 16, 0), lang="en", vitals=rows)
    assert "HR 121" in text
    assert "17:10" not in text


def test_an_earlier_reading_is_not_repeated_while_the_patient_is_still_unstable() -> None:
    rows = [
        _vs("2026-09-01T17:10:00", 136, spo2=88.0, news2_score=9),
        _vs("2026-09-01T22:00:00", 134, spo2=89.0, temperature_celsius=39.5, news2_score=8),
    ]
    text = _shift_note(1, "evening", datetime(2026, 9, 1, 16, 0), lang="en", vitals=rows)
    assert "HR 134" in text
    assert "17:10" not in text


def test_a_stable_shift_has_no_unstable_reading_line() -> None:
    rows = [_vs("2026-09-01T17:10:00", 88, news2_score=1), _vs("2026-09-01T22:00:00", 92, news2_score=0)]
    text = _shift_note(1, "evening", datetime(2026, 9, 1, 16, 0), lang="en", vitals=rows)
    assert "17:10" not in text


def test_vitals_in_window_is_half_open() -> None:
    start, end = datetime(2026, 9, 1, 8, 0), datetime(2026, 9, 1, 16, 0)
    rows = [_vs("2026-09-01T08:00:00", 1), _vs("2026-09-01T15:59:00", 2), _vs("2026-09-01T16:00:00", 3)]
    assert [r["heart_rate"] for r in vitals_in_window(rows, start, end)] == [1, 2]


# ── #3240: no final length of stay in nursing notes ───────────────────────


@pytest.mark.parametrize("lang", ["ja", "en"])
def test_shift_header_does_not_state_the_actual_los(lang: str) -> None:
    text = _shift_note(1, "day", datetime(2026, 9, 1, 8, 0), lang=lang, los_days=11)
    header = text.splitlines()[0]
    assert "11" not in header
    assert "入院予定" not in header and "LOS" not in header
    assert ("入院 2 日目" in header) if lang == "ja" else ("Day 2" in header)


def test_los_estimate_without_protocol_data_is_not_the_realized_los() -> None:
    ctx = _ctx(datetime(2026, 8, 31, 9, 54), los_days=11)
    gen = TemplateNarrativeGenerator()
    acp, facts = build_acp_estimated_los(gen, ctx)
    rp, _ = build_rp_discharge_estimate(gen, ctx)
    assert "11" not in acp and "未定" in acp
    assert "11" not in rp and "未定" in rp
    assert "ctx.los_days" not in facts
