"""A level of consciousness that stays below Alert is named in the progress
note's Assessment as a problem with its cause work-up, delirium as one
differential (Issue #3471). AVPU comes from the physiology, so delirium
itself is named only when the stay records a delirium complication."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from clinosim.modules.document.narrative._progress_exam import consciousness_assessment_line
from clinosim.modules.document.narrative.renderers._composers import compose_progress_assessment_from_state

pytestmark = pytest.mark.unit

_ADM = datetime(2026, 5, 1, 10, 0)


def _v(day: int, level: str) -> dict:
    return {"timestamp": datetime(2026, 5, 1 + day, 8, 0).isoformat(), "consciousness_level": level}


def _ctx(levels: list[str], *, lang: str = "ja", events=None) -> SimpleNamespace:
    return SimpleNamespace(
        target_lang=lang,
        vitals=[_v(d, lv) for d, lv in enumerate(levels)],
        day_index=len(levels) - 1,
        los_days=8,
        severity="moderate",
        encounter={"encounter_id": "E1", "admission_datetime": _ADM},
        patient={"date_of_birth": "1940-01-01"},
        disease_protocol=SimpleNamespace(disease_id="sepsis"),
        authored_datetime=None,
        procedures=[],
        complications_events=events or [],
        complications_occurred=[],
        lab_results=[],
        medications=[],
        orders=[],
        diagnoses=[],
        allergies=[],
    )


def test_three_days_below_alert_names_the_differential_not_a_diagnosis_ja() -> None:
    text = compose_progress_assessment_from_state(_ctx(["V", "P", "P"]))
    assert "意識レベル低下が持続 (AVPU P、3日間)" in text
    assert "せん妄を含む鑑別" in text and "薬剤" in text and "低酸素" in text
    assert "せん妄と診断" not in text and "せん妄を合併" not in text


def test_en_wording() -> None:
    text = compose_progress_assessment_from_state(_ctx(["P", "P"], lang="en"))
    assert "AVPU P, 2 days" in text and "including delirium" in text and "hypoxia" in text
    assert "意識" not in text


def test_alert_or_single_day_writes_nothing() -> None:
    assert "意識レベル低下が持続" not in compose_progress_assessment_from_state(_ctx(["P", "P", "A"]))
    assert "意識レベル低下が持続" not in compose_progress_assessment_from_state(_ctx(["A", "A", "P"]))


def test_recorded_delirium_is_named() -> None:
    events = [{"name": "delirium", "onset_day": 0}]
    text = compose_progress_assessment_from_state(_ctx(["V", "V", "V"], events=events))
    assert "せん妄の原因検索" in text and "鑑別" not in text
    en = compose_progress_assessment_from_state(_ctx(["V", "V"], lang="en", events=events))
    assert "cause of delirium" in en


def test_pure_function_counts_consecutive_days() -> None:
    daily = [[_v(2, "V")], [_v(1, "A")], [_v(0, "V")]]
    assert consciousness_assessment_line(daily, [], "en") == ""
    daily = [[_v(3, "V")], [_v(2, "V")], [_v(1, "A")]]
    assert "2 days" in consciousness_assessment_line(daily, [], "en")
