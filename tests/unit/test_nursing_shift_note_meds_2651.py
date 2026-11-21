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


# Issue #3395: a note quotes nothing recorded after it was written, and does
# not word a single dose as continued.


def _note_at(authored: str | None, lang: str = "en") -> str:
    ctx = SimpleNamespace(
        target_lang=lang,
        day_index=22,
        los_days=24,
        shift="day",
        encounter={"admission_datetime": "2025-03-01T10:00:00"},
        roster_map={},
        vitals=[
            {"timestamp": "2025-03-23T09:00:00", "heart_rate": 80},
            {"timestamp": "2025-03-23T15:00:00", "heart_rate": 133},
        ],
        medications=_MARS,
        nursing_risk_assessments=[],
        authored_datetime=authored,
    )
    return render_nursing_shift_note(ctx, None).raw_text


def test_a_note_authored_before_the_end_of_the_window_quotes_nothing_later() -> None:
    text = _note_at("2025-03-23T12:00:00")
    assert "HR 80" in text and "133" not in text
    full = _note_at("2025-03-23T16:00:00")
    assert "133" in full


def test_the_drug_line_head_does_not_say_continued() -> None:
    ja = _note_at("2025-03-23T16:00:00", lang="ja")
    assert "投薬継続" not in ja and "与薬" in ja


# Issue #3459: every distinct drug given in the shift is listed, not three.


def _shift_text(mars: list[dict], lang: str = "en") -> str:
    ctx = SimpleNamespace(
        target_lang=lang,
        day_index=3,
        los_days=10,
        shift="day",
        encounter={"admission_datetime": "2025-03-01T10:00:00"},
        roster_map={},
        vitals=[],
        medications=mars,
        nursing_risk_assessments=[],
    )
    return render_nursing_shift_note(ctx, None).raw_text


def test_all_drugs_of_the_shift_are_listed_in_first_given_order() -> None:
    names = ["Ceftriaxone", "Enoxaparin", "Furosemide", "Metformin", "Aspirin", "Pantoprazole"]
    mars = [_mar(n, f"2025-03-04T{8 + i:02d}:00:00") for i, n in enumerate(names)]
    mars.append(_mar("Ondansetron", "2025-03-04T12:00:00", status="held"))
    text = _shift_text(mars)
    positions = [text.index(n) for n in names]
    assert positions == sorted(positions)
    assert "Ondansetron" not in text


def test_a_drug_given_twice_is_listed_once() -> None:
    mars = [_mar("Ceftriaxone", "2025-03-04T08:00:00"), _mar("Ceftriaxone", "2025-03-04T15:00:00")]
    assert _shift_text(mars).count("Ceftriaxone") == 1
