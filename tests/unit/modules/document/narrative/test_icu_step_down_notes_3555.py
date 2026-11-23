"""The notes of a stay that left the ICU say so (Issue #3555): the progress
note of the step-down day, the nursing shift note of that shift, and the ICU
dates in the discharge summary; nothing claims the ICU after the step-down."""

from __future__ import annotations

import pytest

from clinosim.modules.document.narrative.renderers.section_builders.discharge_summary import compose_hospital_course
from tests.unit.modules.document.narrative.test_icu_stay_notes_3555 import _assessment, _ctx, _shift

pytestmark = pytest.mark.unit

# Transfer on hospital day 3 (day index 2, 2026-07-11 09:00), step-down on hospital
# day 6 (day index 5, 2026-07-14 09:00).
_SD = {"icu_discharge_day": 5}


def test_progress_note_of_the_step_down_day_says_the_return_to_the_ward() -> None:
    en = _assessment("en", 5, **_SD)
    assert "Transferred back to the general ward from the ICU on hospital day 6." in en
    assert "In the ICU since" not in en
    ja = _assessment("ja", 5, **_SD)
    assert "入院6日目、ICUから一般病棟へ転棟。" in ja
    assert "ICU管理中" not in ja


def test_progress_notes_in_the_icu_before_the_step_down_still_name_the_icu() -> None:
    assert "In the ICU since hospital day 3." in _assessment("en", 4, **_SD)
    # Written on the step-down day before the step-down's time.
    assert "In the ICU since hospital day 3." in _assessment("en", 5, hour=5, **_SD)


def test_progress_notes_after_the_step_down_do_not_name_the_icu() -> None:
    for lang in ("en", "ja"):
        assert "ICU" not in _assessment(lang, 6, **_SD)
        assert "ICU" not in _assessment(lang, 7, **_SD)


def test_nursing_shift_notes_stop_naming_the_icu_after_the_step_down_shift() -> None:
    assert "In the ICU (transferred on hospital day 3)." in _shift("en", 4, "day", 17, **_SD)[0]
    step, _ = _shift("en", 5, "day", 17, **_SD)
    assert "Transferred back to the general ward from the ICU during this shift." in step
    assert "In the ICU" not in step
    assert "ICU" not in _shift("en", 6, "day", 17, **_SD)[0]
    assert "当シフト中にICUから一般病棟へ転棟。" in _shift("ja", 5, "day", 17, **_SD)[0]
    assert "ICU" not in _shift("ja", 6, "day", 17, **_SD)[0]


def test_discharge_summary_states_the_icu_dates() -> None:
    en, facts = compose_hospital_course(_ctx("en", 8, hour=11, **_SD))
    assert "from 2026-07-11 (hospital day 3) to 2026-07-14 (hospital day 6)" in en
    assert "transferred back to the general ward" in en
    assert "ctx.icu_discharge_day" in facts
    ja, _ = compose_hospital_course(_ctx("ja", 8, hour=11, **_SD))
    assert "入院3日目（2026-07-11）から6日目（2026-07-14）まで集中治療室（ICU）で管理し、一般病棟へ転棟した。" in ja


def test_a_stay_still_in_the_icu_at_discharge_keeps_the_transfer_clause() -> None:
    en, facts = compose_hospital_course(_ctx("en", 8, hour=11))
    assert "Transferred to the intensive care unit (ICU) on hospital day 3 (2026-07-11)" in en
    assert "general ward" not in en and "ctx.icu_discharge_day" not in facts
