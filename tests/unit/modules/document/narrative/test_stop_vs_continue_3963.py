"""Issue #3963: a progress note says one thing about each drug at its own time.

The "Continue current medications" list and the "... was discontinued on day N"
line of a note both read the stop orders (``DISCONTINUE`` markers) as they stood
at the note's authored time (``_medication_plan.drug_stop_status``): a drug
whose stop order is placed after the note is still continued and has no stop
line; a drug whose stop order falls in the note's period is under "Stopped" and
has the stop line once; the notes after it repeat neither.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from clinosim.modules.document.narrative._medication_plan import drug_stop_status, note_medications
from clinosim.modules.document.narrative._safety_skips import progress_note_safety_skips
from clinosim.modules.document.narrative._template_helpers import _render_safety_skips_line
from clinosim.modules.document.narrative.renderers._composers import compose_progress_plan_from_state

ADMITTED = datetime(2026, 4, 2, 14, 0)
STOP_ORDER = "2026-04-11T13:00:00"
NAMES = {"en": "Ceftriaxone", "ja": "セフトリアキソン"}


def _dose(name: str, when: datetime, order_id: str) -> dict:
    return {
        "drug_name": name,
        "drug_id": name.casefold(),
        "scheduled_datetime": when.isoformat(),
        "actual_datetime": when.isoformat(),
        "status": "given",
        "order_id": order_id,
        "route": "IV",
    }


def _doses(name: str, first: datetime, last: datetime, order_id: str) -> list[dict]:
    out, when = [], first
    while when <= last:
        out.append(_dose(name, when, order_id))
        when += timedelta(days=1)
    return out


def _marker(drug: str, ordered: str) -> dict:
    return {
        "order_id": f"ORD-E-STOP-D9-0-{drug[:8].lower()}",
        "order_type": "medication",
        "display_name": f"DISCONTINUE: {drug}",
        "ordered_datetime": ordered,
        "frequency": "",
        "single_dose": False,
    }


def _ctx(
    lang: str, authored: str, *, last_dose: datetime = datetime(2026, 4, 11, 8, 0), extra_doses=()
) -> SimpleNamespace:
    as_of = datetime.fromisoformat(authored)
    meds = _doses("Ceftriaxone", datetime(2026, 4, 3, 8, 0), last_dose, "O-CTRX")
    meds += _doses("Heparin", datetime(2026, 4, 3, 8, 0), datetime(2026, 4, 13, 8, 0), "O-HEP")
    meds += list(extra_doses)
    orders = [
        {"order_id": "O-CTRX", "order_type": "medication", "frequency": "DAILY", "single_dose": False},
        {"order_id": "O-HEP", "order_type": "medication", "frequency": "DAILY", "single_dose": False},
        _marker("Ceftriaxone", STOP_ORDER),
    ]
    return SimpleNamespace(
        target_lang=lang,
        day_index=(as_of.date() - ADMITTED.date()).days,
        medications=meds,
        procedures=[],
        orders=orders,
        encounter=SimpleNamespace(admission_datetime=ADMITTED.isoformat()),
        authored_datetime=as_of,
    )


def _skip(lang: str) -> dict:
    # ``stopped_on_day`` is the day the drug last ran (9), one before the day of
    # the stop order (10): the time of the order decides, not the day.
    return {
        "considered": "Ceftriaxone",
        "considered_ja": "セフトリアキソン",
        "avoided_due_to": "treatment plan change",
        "avoided_due_to_ja": "治療計画変更",
        "substituted_with": None,
        "event_type": "switch",
        "rule_id": "treatment-modification-switch",
        "stopped_on_day": 9,
    }


def _stop_lines(ctx: SimpleNamespace) -> str:
    kept = progress_note_safety_skips(
        [_skip(ctx.target_lang)],
        note_medications(ctx).held_refs,
        hospital_day=int(ctx.day_index) + 1,
        stops=drug_stop_status(ctx),
    )
    return _render_safety_skips_line(kept, ctx.target_lang)


def _continued(plan: str, lang: str) -> str:
    marker = "Continue current medications:" if lang == "en" else "薬物療法継続:"
    return re.split(r"[.。]", plan.split(marker, 1)[1], maxsplit=1)[0] if marker in plan else ""


@pytest.mark.parametrize("lang", ["en", "ja"])
def test_note_before_the_stop_order_continues_the_drug_and_states_no_stop(lang: str) -> None:
    ctx = _ctx(lang, "2026-04-11T05:00:00")
    assert NAMES[lang] in _continued(compose_progress_plan_from_state(ctx), lang)
    assert _stop_lines(ctx) == ""


@pytest.mark.parametrize("lang", ["en", "ja"])
def test_note_after_the_stop_order_states_the_stop_once_and_does_not_continue_it(lang: str) -> None:
    ctx = _ctx(lang, "2026-04-11T16:51:00")
    plan = compose_progress_plan_from_state(ctx)
    assert NAMES[lang] not in _continued(plan, lang)
    stopped_marker = "Stopped:" if lang == "en" else "中止:"
    assert NAMES[lang] in plan.split(stopped_marker, 1)[1]
    line = _stop_lines(ctx)
    assert line.count(NAMES[lang]) == 1
    assert ("discontinued" if lang == "en" else "中止") in line


@pytest.mark.parametrize("lang", ["en", "ja"])
def test_notes_after_the_reporting_note_repeat_neither_line(lang: str) -> None:
    for authored in ("2026-04-12T16:51:00", "2026-04-13T16:51:00"):
        ctx = _ctx(lang, authored)
        plan = compose_progress_plan_from_state(ctx)
        assert NAMES[lang] not in plan
        assert _stop_lines(ctx) == ""


@pytest.mark.parametrize("lang", ["en", "ja"])
def test_a_drug_never_both_continued_and_stopped_in_one_note(lang: str) -> None:
    for authored in ("2026-04-10T16:51:00", "2026-04-11T12:59:00", "2026-04-11T13:01:00", "2026-04-11T16:51:00"):
        ctx = _ctx(lang, authored)
        in_continue = NAMES[lang] in _continued(compose_progress_plan_from_state(ctx), lang)
        stop_line = NAMES[lang] in _stop_lines(ctx)
        assert not (in_continue and stop_line), authored


@pytest.mark.parametrize("lang", ["en", "ja"])
def test_a_dose_after_the_stop_order_keeps_the_drug_running(lang: str) -> None:
    """A drug given again after the order (the dose is in the record) is not stopped."""
    late = _dose("Ceftriaxone", datetime(2026, 4, 11, 15, 0), "O-CTRX")
    ctx = _ctx(lang, "2026-04-11T16:51:00", extra_doses=[late])
    assert drug_stop_status(ctx) == {}
    assert NAMES[lang] in _continued(compose_progress_plan_from_state(ctx), lang)
    assert _stop_lines(ctx) == ""


def test_status_names_the_note_that_reports_the_stop() -> None:
    assert drug_stop_status(_ctx("en", "2026-04-11T05:00:00")) == {}
    assert drug_stop_status(_ctx("en", "2026-04-11T16:51:00")) == {"ceftriaxone": "now"}
    assert drug_stop_status(_ctx("en", "2026-04-12T16:51:00")) == {"ceftriaxone": "earlier"}


def test_without_an_authored_time_the_hospital_day_decides() -> None:
    """A note with no authored time reads the stop order by its calendar day."""
    day_of = _ctx("en", "2026-04-11T16:51:00")
    day_of.authored_datetime = None
    assert drug_stop_status(day_of) == {"ceftriaxone": "now"}
    after = _ctx("en", "2026-04-12T16:51:00")
    after.authored_datetime = None
    assert drug_stop_status(after) == {"ceftriaxone": "earlier"}


def test_en_text_has_no_japanese() -> None:
    ctx = _ctx("en", "2026-04-11T16:51:00")
    text = compose_progress_plan_from_state(ctx) + _stop_lines(ctx)
    assert not any("぀" <= ch <= "鿿" for ch in text)
