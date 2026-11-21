"""A note lists procedures done by its authored time (Issue #3468).

A procedure that starts later the same calendar day is not "done" when the
H&P or progress note is written: it is worded as planned.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from clinosim.modules.document.narrative._as_of import procedures_after, procedures_started_by
from clinosim.modules.document.narrative.renderers._shared_helpers import procedure_prose_name
from clinosim.modules.document.narrative.template_generator import TemplateNarrativeGenerator
from clinosim.types.document import DocumentType
from tests.unit.modules.document.narrative.test_procedure_names_3246 import _ctx, _proc

_PHRASES = {
    ("hp", "en"): ("Workup / procedures:", "Planned procedures:"),
    ("hp", "ja"): ("検査・処置:", "予定処置:"),
    ("pn", "en"): ("Procedures today:", "Planned later today:"),
    ("pn", "ja"): ("本日の処置:", "本日予定の処置:"),
}


def _plan(kind: str, lang: str, authored: datetime | None) -> tuple[str, str]:
    procs = [_proc("urinary_catheter", "51702", "J063", "2026-09-01T20:53:00", lang=lang)]
    gen = TemplateNarrativeGenerator()
    if kind == "hp":
        ctx = _ctx(lang, procs, doc=DocumentType.ADMISSION_HP)
        ctx.authored_datetime = authored
        return gen._compose_ap_plan_from_state(ctx), procedure_prose_name(procs[0], lang)
    ctx = _ctx(lang, procs, day_index=0, doc=DocumentType.PROGRESS_NOTE)
    ctx.authored_datetime = authored
    return gen._compose_progress_plan_from_state(ctx), procedure_prose_name(procs[0], lang)


@pytest.mark.parametrize("kind", ["hp", "pn"])
@pytest.mark.parametrize("lang", ["en", "ja"])
def test_later_same_day_procedure_is_planned_not_done(kind: str, lang: str) -> None:
    done, planned = _PHRASES[(kind, lang)]
    text, name = _plan(kind, lang, datetime(2026, 9, 1, 13, 19))
    assert done not in text
    assert f"{planned} {name}" in text


@pytest.mark.parametrize("kind", ["hp", "pn"])
@pytest.mark.parametrize("lang", ["en", "ja"])
@pytest.mark.parametrize("authored", [datetime(2026, 9, 1, 21, 30), None])
def test_started_procedure_or_no_authored_time_is_done(kind: str, lang: str, authored: datetime | None) -> None:
    done, planned = _PHRASES[(kind, lang)]
    text, name = _plan(kind, lang, authored)
    assert f"{done} {name}" in text
    assert planned not in text


def test_as_of_helpers_split_and_ignore_timezone() -> None:
    rows = [{"start_datetime": "2026-09-01T12:00:00+09:00"}, {"start_datetime": "2026-09-01T20:00:00"}, {}]
    cut = datetime(2026, 9, 1, 14, 0)
    assert procedures_started_by(rows, cut) == [rows[0], rows[2]]
    assert procedures_after(rows, cut) == [rows[1]]
    assert procedures_started_by(rows, None) == rows
    assert procedures_after(rows, None) == []
