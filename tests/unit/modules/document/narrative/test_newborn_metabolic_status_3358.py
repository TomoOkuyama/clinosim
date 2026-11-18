"""One status of the newborn metabolic screen at a document's time (Issue #3358).

Not collected: nothing is said. Collected, not yet reported: submitted, result
pending. At or after the result time: the result.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from clinosim.modules.document.narrative.context import newborn_metabolic_status, newborn_workup_known_at
from clinosim.modules.document.narrative.renderers._composers import newborn_screening_to_date
from clinosim.modules.document.narrative.renderers.section_builders.discharge_summary import compose_hospital_course
from clinosim.modules.document.narrative.renderers.section_builders.hpi import _maybe_append_newborn_workup
from tests.unit.modules.document.narrative.test_admission_hp_complete_3245 import _baby

pytestmark = pytest.mark.unit

_COLLECTED = datetime(2025, 12, 23, 10, 36)
_RESULT = datetime(2025, 12, 27, 12, 0)


def _workup(**over: object) -> dict:
    base = {
        "is_neonate": True,
        "has_metabolic": True,
        "event_times": {"metabolic": _COLLECTED.isoformat()},
        "metabolic_result_datetime": _RESULT.isoformat(),
        "metabolic_outcome_key": "pass",
    }
    base.update(over)
    return base


def test_status_helper_three_states_and_boundaries() -> None:
    w = _workup()
    assert newborn_metabolic_status(w, datetime(2025, 12, 23, 10, 35)) == "not_collected"
    assert newborn_metabolic_status(w, _COLLECTED) == "pending"
    assert newborn_metabolic_status(w, datetime(2025, 12, 27, 11, 59)) == "pending"
    assert newborn_metabolic_status(w, _RESULT) == "resulted"
    assert newborn_metabolic_status(w, datetime(2026, 1, 5)) == "resulted"
    # No document time: the result is never stated.
    assert newborn_metabolic_status(w, None) == "pending"
    # Never done / no result time in the record.
    assert newborn_metabolic_status(_workup(has_metabolic=False), _RESULT) == "not_collected"
    assert newborn_metabolic_status(_workup(metabolic_result_datetime=None), datetime(2026, 1, 5)) == "pending"


def test_known_at_hides_a_screen_not_yet_collected_and_carries_the_status() -> None:
    before = newborn_workup_known_at(_workup(), datetime(2025, 12, 22, 12, 0))
    assert before["has_metabolic"] is False and before["metabolic_status"] == "not_collected"
    mid = newborn_workup_known_at(_workup(), datetime(2025, 12, 25, 12, 0))
    assert mid["has_metabolic"] is True and mid["metabolic_status"] == "pending"


def _baby_screen(lang: str, authored: datetime, outcome: str = "pass"):
    ctx = _baby(lang, {})
    ctx.newborn_workup.update(_workup(metabolic_outcome_key=outcome))
    ctx.newborn_workup["event_times"]["aabr"] = "2025-12-23T10:36:00"
    ctx.authored_datetime = authored
    return ctx


_PHRASES = {
    "en": ("submitted, result pending", "no abnormality detected", "referred for confirmatory testing"),
    "ja": ("結果待ち", "異常なし", "要精査"),
}


@pytest.mark.parametrize("lang", ["en", "ja"])
def test_hp_says_nothing_then_pending_then_the_result(lang: str) -> None:
    pending, ok, refer = _PHRASES[lang]
    texts = {}
    for key, at in (
        ("before", datetime(2025, 12, 23, 9, 0)),
        ("mid", datetime(2025, 12, 25, 9, 0)),
        ("after", _RESULT),
    ):
        ctx = _baby_screen(lang, at)
        texts[key] = _maybe_append_newborn_workup("", [], ctx)[0]
    assert pending not in texts["before"] and ok not in texts["before"]
    assert pending in texts["mid"] and ok not in texts["mid"]
    assert ok in texts["after"] and pending not in texts["after"]
    assert refer in _maybe_append_newborn_workup("", [], _baby_screen(lang, _RESULT, "refer"))[0]


@pytest.mark.parametrize("lang", ["en", "ja"])
def test_discharge_summary_gives_the_result_only_from_the_result_time(lang: str) -> None:
    pending, ok, _ = _PHRASES[lang]
    mid = compose_hospital_course(_baby_screen(lang, datetime(2025, 12, 25, 9, 0)))[0]
    after = compose_hospital_course(_baby_screen(lang, datetime(2025, 12, 28, 9, 0)))[0]
    assert pending in mid and ok not in mid
    assert ok in after and pending not in after
    assert ok in newborn_screening_to_date(_baby_screen(lang, _RESULT))
    assert "代謝" not in newborn_screening_to_date(_baby_screen(lang, datetime(2025, 12, 22, 9, 0)))
