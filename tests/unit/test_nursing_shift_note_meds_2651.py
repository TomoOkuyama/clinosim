"""Issue #2651: a shift note lists the drugs given in that shift."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from clinosim.modules.document.narrative.renderers.nursing_shift_note import render_nursing_shift_note

pytestmark = pytest.mark.unit


def _mar(name: str, when: str, status: str = "given") -> dict:
    return {"drug_name": name, "actual_datetime": when, "scheduled_datetime": when, "status": status}


_MARS = [
    _mar("Crystalloid 30 mL/kg bolus", "2025-03-01T10:30:00"),  # day 0
    _mar("Ceftriaxone", "2025-03-23T09:00:00"),  # day 22, day shift
    _mar("Acetaminophen", "2025-03-23T13:00:00", status="held"),  # day 22, not given
    _mar("Enoxaparin", "2025-03-23T21:00:00"),  # day 22, evening shift
]


def _note(day: int, shift: str) -> str:
    ctx = SimpleNamespace(
        target_lang="en",
        day_index=day,
        los_days=24,
        shift=shift,
        encounter={"admission_datetime": "2025-03-01T10:00:00"},
        roster_map={},
        vitals=[],
        medications=_MARS,
        nursing_risk_assessments=[],
    )
    return render_nursing_shift_note(ctx, None).raw_text


def test_a_late_day_note_does_not_list_the_day_zero_bolus() -> None:
    text = _note(22, "day")
    assert "Crystalloid" not in text
    assert "Ceftriaxone" in text


def test_only_what_was_given_in_the_shift_is_listed() -> None:
    day, evening = _note(22, "day"), _note(22, "evening")
    assert "Acetaminophen" not in day  # held, not given
    assert "Enoxaparin" not in day and "Enoxaparin" in evening
    assert "Ceftriaxone" not in evening


def test_a_note_without_a_shift_covers_the_calendar_day() -> None:
    text = _note(22, "")
    assert "Ceftriaxone" in text and "Enoxaparin" in text and "Crystalloid" not in text


def test_the_admission_day_note_lists_the_bolus() -> None:
    assert "Crystalloid" in _note(0, "day")
