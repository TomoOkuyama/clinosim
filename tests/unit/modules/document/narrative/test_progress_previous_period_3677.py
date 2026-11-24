"""A daily note's "previous period" is the period the previous note covered
(Issue #3677): the readings between two notes authored ~20 h apart are not
dropped, a patient already on oxygen in the previous note is "persisting", and
the previous value quoted in the breathing sentence is the previous note's
latest reading."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from clinosim.modules.document.narrative._progress_exam import course_line
from clinosim.modules.document.narrative._progress_state import finding_states
from clinosim.modules.document.narrative._progress_symptoms import respiratory_symptom_line
from clinosim.modules.document.narrative.renderers._composers import _note_period_vitals
from tests.unit.modules.document.narrative.test_progress_exam_course_3235_3247 import _ctx

pytestmark = pytest.mark.unit

_O2 = ("spo2", "low")


def _r(when: datetime, **fields) -> dict:
    return {"timestamp": when.isoformat(), **fields}


def _stay(authored_prev: datetime | None, authored: datetime):
    # a room-air reading 40 h before the second note; oxygen starts 23 h before it,
    # i.e. 3 h before the previous note: after the fixed (as_of-48h, as_of-24h]
    # window, so the legacy comparison sees room air only
    vitals = [
        _r(authored - timedelta(hours=40), spo2=97.0, respiratory_rate=18, on_supplemental_oxygen=False),
        _r(
            authored - timedelta(hours=23),
            spo2=91.0,
            respiratory_rate=23,
            on_supplemental_oxygen=True,
            oxygen_device="NRB",
        ),
        _r(
            authored - timedelta(hours=22),
            spo2=91.0,
            respiratory_rate=23,
            on_supplemental_oxygen=True,
            oxygen_device="NRB",
        ),
        _r(
            authored - timedelta(hours=3),
            spo2=87.0,
            respiratory_rate=26,
            on_supplemental_oxygen=True,
            oxygen_device="NRB",
        ),
    ]
    ctx = _ctx(vitals, day=2, lang="en")
    ctx.authored_datetime = authored
    ctx.previous_authored_datetime = authored_prev
    return ctx


_NOTE = datetime(2026, 5, 3, 16, 0)
_PREV = _NOTE - timedelta(hours=20)


def test_previous_period_ends_at_the_previous_note() -> None:
    ctx = _stay(_PREV, _NOTE)
    prev = _note_period_vitals(ctx, previous=True)
    assert prev and max(r["timestamp"] for r in prev) == (_NOTE - timedelta(hours=22)).isoformat()
    assert all(datetime.fromisoformat(r["timestamp"]) <= _PREV for r in prev)


def test_first_note_keeps_the_legacy_window() -> None:
    ctx = _stay(None, _NOTE)
    prev = _note_period_vitals(ctx, previous=True)
    assert [r["timestamp"] for r in prev] == [(_NOTE - timedelta(hours=40)).isoformat()]


def test_oxygen_already_on_in_previous_note_is_persisting() -> None:
    ctx = _stay(_PREV, _NOTE)
    cur, prev = _note_period_vitals(ctx), _note_period_vitals(ctx, previous=True)
    assert finding_states(ctx, cur, prev)[_O2] in {"persisting", "improving"}
    assert "new oxygen" not in course_line(ctx, cur, prev, "en")


def test_legacy_window_would_call_it_new() -> None:
    ctx = _stay(None, _NOTE)
    cur, prev = _note_period_vitals(ctx), _note_period_vitals(ctx, previous=True)
    assert finding_states(ctx, cur, prev)[_O2] == "new"


def test_notes_more_than_a_window_apart_leave_no_gap() -> None:
    note = datetime(2026, 5, 5, 16, 0)
    ctx = _stay(note - timedelta(hours=40), note)
    ctx.vitals.append(_r(note - timedelta(hours=30), spo2=95.0))
    cur = _note_period_vitals(ctx)
    assert any(r["timestamp"] == (note - timedelta(hours=30)).isoformat() for r in cur)


def test_previous_value_in_breathing_sentence_is_the_previous_notes_reading() -> None:
    ctx = _stay(_PREV, _NOTE)
    ctx.disease_protocol.disease_id = "bacterial_pneumonia"
    cur, prev = _note_period_vitals(ctx), _note_period_vitals(ctx, previous=True)
    line = respiratory_symptom_line(ctx, cur, prev)
    assert "RR 23 → 26" in line and "SpO2 91 → 87" in line
