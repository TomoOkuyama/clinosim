"""Issue #3445: the shift note names the nurse who wrote it (the rotated
author), not the admission's primary nurse."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from clinosim.modules.document.narrative.renderers.nursing_shift_note import render_nursing_shift_note

pytestmark = pytest.mark.unit

_ROSTER = {"NS-A": {"name": "Aoki"}, "NS-B": {"name": "Baba"}}


def _ctx(lang: str, author: str) -> SimpleNamespace:
    return SimpleNamespace(
        target_lang=lang,
        locale="jp" if lang == "ja" else "us",
        authored_datetime=None,
        author_practitioner_id=author,
        day_index=0,
        los_days=3,
        shift="day",
        encounter={"admission_datetime": "2026-08-31T09:54:00", "primary_nurse_id": "NS-B"},
        roster_map=_ROSTER,
        vitals=[],
        medications=[],
        adl_assessments=[],
        nursing_risk_assessments=[],
        patient={"bmi": 22.0, "chronic_conditions": []},
        disease_protocol=None,
    )


def _text(ctx: SimpleNamespace) -> str:
    return render_nursing_shift_note(ctx, None).raw_text


@pytest.mark.parametrize(("lang", "label"), [("ja", "記録者: "), ("en", "Recorded by: ")])
def test_author_is_named_not_primary_nurse(lang: str, label: str) -> None:
    out = _text(_ctx(lang, "NS-A"))
    assert f"{label}Aoki" in out
    assert "Baba" not in out


def test_empty_author_falls_back_to_primary_nurse() -> None:
    out = _text(_ctx("en", ""))
    assert "Recorded by: Baba" in out
