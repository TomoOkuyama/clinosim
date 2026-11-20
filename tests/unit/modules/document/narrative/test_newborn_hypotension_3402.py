"""A newborn's ordinary systolic pressure is not called hypotension in a
progress note (Issue #3402): the low limit of a child's systolic pressure is
the PALS hypotension threshold, not the normal-range lower edge."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from clinosim.modules.document.narrative._narrative_interpretation_thresholds import progress_vitals_rules
from clinosim.modules.document.narrative._progress_exam import period_states, progress_exam_rules
from clinosim.modules.document.narrative.renderers._composers import _vital_limit, compose_today_vitals_line
from clinosim.modules.observation.pediatric_ranges import pediatric_vital_range

pytestmark = pytest.mark.unit

_ADM = datetime(2026, 5, 1, 10, 0)


def _ctx(dob: str, sbp: float, lang: str = "ja") -> SimpleNamespace:
    reading = {"timestamp": datetime(2026, 5, 2, 8, 0).isoformat(), "systolic_bp": sbp, "heart_rate": 130}
    return SimpleNamespace(
        target_lang=lang,
        vitals=[reading],
        day_index=1,
        encounter={"encounter_id": "E1", "admission_datetime": _ADM},
        patient={"date_of_birth": dob},
        authored_datetime=None,
    )


def _reading(sbp: float) -> dict:
    return {"timestamp": datetime(2026, 5, 2, 8, 0).isoformat(), "systolic_bp": sbp}


@pytest.mark.parametrize("sbp, expected", [(63, {"normal"}), (60, {"normal"}), (59, {"low"}), (55, {"low"})])
def test_newborn_systolic_state_uses_hypotension_threshold(sbp: float, expected: set[str]) -> None:
    ctx = _ctx("2026-05-01", sbp)
    assert period_states(ctx, [_reading(sbp)])["systolic_bp"] == expected


def test_adult_systolic_state_unchanged() -> None:
    ctx = _ctx("1950-01-01", 85)
    assert period_states(ctx, [_reading(85)])["systolic_bp"] == {"low"}
    assert period_states(_ctx("1950-01-01", 95), [_reading(95)])["systolic_bp"] == {"normal"}


def test_newborn_extreme_limit_is_hypotension_bound() -> None:
    ctx = _ctx("2026-05-01", 63)
    assert _vital_limit(ctx, "systolic_bp", "min", 90, "critical_low") == 60
    assert _vital_limit(ctx, "systolic_bp", "min", 90) == 67  # normal-range edge when not asked for
    assert _vital_limit(_ctx("1950-01-01", 63), "systolic_bp", "min", 90, "critical_low") == 90


@pytest.mark.parametrize("lang, word", [("ja", "収縮期血圧"), ("en", "systolic")])
def test_newborn_vitals_line_has_no_low_bp_extreme_at_63(lang: str, word: str) -> None:
    ctx = _ctx("2026-05-01", 70, lang)
    ctx.vitals = [
        {"timestamp": datetime(2026, 5, 2, 2, 0).isoformat(), "systolic_bp": 63, "heart_rate": 130},
        {"timestamp": datetime(2026, 5, 2, 8, 0).isoformat(), "systolic_bp": 70, "heart_rate": 130},
    ]
    line = compose_today_vitals_line(ctx)
    assert "63" not in line.split("最低")[-1] if lang == "ja" else "63" not in line.lower().split("min")[-1]
    ctx.vitals[0]["systolic_bp"] = 55
    assert "55" in compose_today_vitals_line(ctx)


def test_child_low_edges_name_a_vital_the_pediatric_ranges_list() -> None:
    named = [v for v, lim in progress_exam_rules().limits.items() if lim.child_low == "critical_low"]
    named += [r.vital for r in progress_vitals_rules().extremes if r.child_low == "critical_low"]
    assert "systolic_bp" in named
    for vital in set(named):
        band = pediatric_vital_range(vital, 0)
        assert band is not None and band.critical_low is not None
