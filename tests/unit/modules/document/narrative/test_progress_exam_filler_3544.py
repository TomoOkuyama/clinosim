"""A progress note's exam says "unchanged" only when the previous note's
findings really are unchanged and nothing new happened in the period; a
comatose patient's neurological findings are stated, and a coma is worked up
for its neurological and structural causes, not as delirium (Issue #3544)."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import patch

import pytest

from clinosim.modules.document.narrative._progress_exam import consciousness_assessment_line
from clinosim.modules.document.narrative.registry import load_document_type_specs
from clinosim.modules.document.narrative.renderers.progress_note import render_progress_note
from clinosim.modules.document.narrative.template_generator import TemplateNarrativeGenerator
from clinosim.types.document import DocumentType
from tests.unit.modules.document.narrative.test_progress_course_followup_3235_3247 import _ctx, _v

pytestmark = pytest.mark.unit

_EXAM = {
    "general": {"all": "意識清明"},
    "cardiovascular": {"all": "整、心雑音なし"},
    "neurological": {"all": "麻痺なし"},
}
_WELL = dict(temperature_celsius=36.8, heart_rate=78, respiratory_rate=16, spo2=98.0)


def _note(vitals: list[dict], *, events=None, day: int = 2) -> str:
    gen = TemplateNarrativeGenerator()
    spec = load_document_type_specs()[DocumentType.PROGRESS_NOTE]
    traj = {"subjective": "", "objective": "", "assessment": "", "plan": ""}
    ctx = _ctx(vitals, day=day)
    ctx.complications_events = events or []
    with (
        patch.object(gen, "_resolve_daily_trajectory_with_source", return_value=(traj, "")),
        patch.object(gen, "_resolve_physical_exam", return_value=_EXAM),
    ):
        return render_progress_note(gen, ctx, spec).sections["objective"]


def test_unchanged_is_still_written_when_nothing_happened() -> None:
    out = _note([_v(1, 8, **_WELL), _v(2, 8, **_WELL)])
    assert "身体所見: 前日と著変なし" in out


def test_a_new_complication_in_the_period_prevents_the_filler() -> None:
    events = [{"name": "pneumonia", "onset_day": 2, "onset_datetime": datetime(2026, 5, 3, 3, 0).isoformat()}]
    out = _note([_v(1, 8, **_WELL), _v(2, 8, **_WELL)], events=events)
    assert "前日と著変なし" not in out
    assert "心雑音なし" in out and "麻痺なし" in out


def test_coma_states_the_neurological_findings_not_unchanged() -> None:
    coma = {**_WELL, "consciousness_level": "U"}
    out = _note([_v(1, 8, **coma), _v(2, 8, **coma)])
    assert "神経: 麻痺なし、刺激に覚醒せず、従命不可" in out
    assert "神経: 前日と著変なし" not in out and "、神経: 前日" not in out


def test_pain_responsive_coma_neurological_line() -> None:
    coma = {**_WELL, "consciousness_level": "P"}
    out = _note([_v(1, 8, **coma), _v(2, 8, **coma)])
    assert "痛み刺激でのみ反応、従命不可" in out


def _daily(levels: list[str]) -> list[list]:
    return [[{"consciousness_level": lv}] for lv in levels]


def test_coma_work_up_is_not_the_delirium_work_up() -> None:
    text = consciousness_assessment_line(_daily(["U", "U"]), [], "ja")
    assert "せん妄" not in text and "頭蓋内病変" in text and "低血糖" in text and "痙攣" in text
    named = consciousness_assessment_line(_daily(["P", "P"]), ["delirium"], "ja")
    assert "せん妄" not in named and "頭蓋内病変" in named


def test_coma_work_up_en() -> None:
    text = consciousness_assessment_line(_daily(["P", "P"]), [], "en")
    assert "delirium" not in text and "intracranial lesion" in text and "hypoglycemia" in text


def test_drowsy_patient_keeps_the_delirium_work_up() -> None:
    text = consciousness_assessment_line(_daily(["V", "V"]), [], "ja")
    assert "せん妄を含む鑑別" in text and "頭蓋内病変" not in text
