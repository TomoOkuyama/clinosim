"""The notes of an ICU-transferred stay say so (Issue #3555): the progress note
of the transfer day and after, the nursing shift note and the discharge summary;
a stay without a transfer has no ICU text, and no step-down is ever stated."""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from clinosim.modules.document.narrative.renderers._composers import compose_progress_assessment_from_state
from clinosim.modules.document.narrative.renderers.nursing_shift_note import render_nursing_shift_note
from clinosim.modules.document.narrative.renderers.section_builders.discharge_summary import compose_hospital_course

pytestmark = pytest.mark.unit

_ADM = datetime(2026, 7, 9, 9, 0)
_ENC = {
    "encounter_id": "E1",
    "admission_datetime": _ADM.isoformat(),
    "discharge_datetime": (_ADM + timedelta(days=8)).isoformat(),
    "primary_nurse_id": "",
}
_SEPSIS = {"name": "sepsis", "onset_day": 2, "onset_datetime": "2026-07-11T13:00:00", "source": "daily_loop"}


def _ctx(lang: str, day: int, *, icu_day: int | None = 2, hour: int = 17, **kw) -> SimpleNamespace:
    base = {
        "target_lang": lang,
        "locale": "jp" if lang == "ja" else "us",
        "authored_datetime": datetime(2026, 7, 9) + timedelta(days=day, hours=hour),
        "day_index": day,
        "shift": "day",
        "encounter": _ENC,
        "icu_transferred": icu_day is not None,
        "icu_transferred_day": -1 if icu_day is None else icu_day,
        "complications_events": [_SEPSIS],
        "complications_occurred": [],
        "working_diagnoses": [],
        "diagnoses": [],
        "roster_map": {},
        "vitals": [],
        "medications": [],
        "lab_results": [],
        "nursing_risk_assessments": [],
        "adl_assessments": [],
        "intake_output_records": [],
        "orders": [],
        "procedures": [],
        "devices": [],
        "newborn_workup": {},
        "patient": {"date_of_birth": "1950-01-01", "weight_kg": 70.0},
        "disease_protocol": None,
        "author_practitioner_id": "",
        "los_days": 8,
    }
    base.update(kw)
    return SimpleNamespace(**base)


def _assessment(lang: str, day: int, **kw) -> str:
    return compose_progress_assessment_from_state(_ctx(lang, day, **kw))


def test_progress_note_on_the_transfer_day_says_the_transfer_and_why() -> None:
    en = _assessment("en", 2)
    assert "Transferred to the intensive care unit (ICU) on hospital day 3 in the setting of" in en
    ja = _assessment("ja", 2)
    assert "入院3日目に集中治療室（ICU）へ転棟" in ja and "を認め" in ja


def test_progress_note_after_the_transfer_names_the_icu_stay() -> None:
    assert "In the ICU since hospital day 3." in _assessment("en", 4)
    assert "ICU管理中（入院3日目にICUへ転棟）。" in _assessment("ja", 4)


def test_progress_note_before_the_transfer_says_nothing() -> None:
    assert "ICU" not in _assessment("en", 1) and "ICU" not in _assessment("ja", 1)
    # Written on the transfer day before the transfer's time.
    assert "ICU" not in _assessment("en", 2, hour=5)


def test_no_step_down_is_claimed() -> None:
    for day in (2, 4, 7):
        text = _assessment("en", day)
        assert "step-down" not in text.lower() and "returned to the ward" not in text.lower()


def test_stay_without_transfer_has_no_icu_text() -> None:
    for lang in ("en", "ja"):
        text = _assessment(lang, 3, icu_day=None, complications_events=[])
        assert "ICU" not in text


def _shift(lang: str, day: int, shift: str, hour: int, **kw) -> tuple[str, list[str]]:
    ctx = _ctx(lang, day, hour=hour, shift=shift, **kw)
    out = render_nursing_shift_note(ctx, SimpleNamespace())
    return out.raw_text, out.facts_used


def test_nursing_shift_names_the_icu_from_the_transfer_shift() -> None:
    # Transfer at 09:00 on hospital day 3 (admission time + 2 days).
    before, _ = _shift("en", 2, "night", 6)
    assert "ICU" not in before
    transfer, facts = _shift("en", 2, "day", 17)
    assert "Transferred to the ICU during this shift." in transfer
    assert "ctx.icu_transferred_day" in facts
    later, _ = _shift("en", 3, "day", 17)
    assert "In the ICU (transferred on hospital day 3)." in later
    assert "ICU管理中（入院3日目にICUへ転棟）。" in _shift("ja", 3, "day", 17)[0]
    assert "当シフト中にICUへ転棟。" in _shift("ja", 2, "day", 17)[0]


def test_nursing_shift_without_transfer_has_no_icu_text() -> None:
    ctx = _ctx("en", 3, icu_day=None)
    assert "ICU" not in render_nursing_shift_note(ctx, SimpleNamespace()).raw_text


def test_discharge_summary_carries_the_icu_clause() -> None:
    en, facts = compose_hospital_course(_ctx("en", 8, hour=11))
    assert "Transferred to the intensive care unit (ICU) on hospital day 3 (2026-07-11) in the setting of" in en
    assert "ctx.icu_transferred_day" in facts
    ja, _ = compose_hospital_course(_ctx("ja", 8, hour=11))
    assert "入院3日目（2026-07-11）に集中治療室（ICU）へ転棟した。" in ja
    assert "step-down" not in en.lower()


def test_discharge_summary_without_transfer_has_no_icu_clause() -> None:
    en, facts = compose_hospital_course(_ctx("en", 8, icu_day=None, hour=11))
    assert "intensive care" not in en and "ctx.icu_transferred_day" not in facts
