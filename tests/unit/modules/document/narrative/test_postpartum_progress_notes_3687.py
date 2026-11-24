"""Issue #3687: the daily progress notes of a delivery stay state the
postpartum day and the postpartum finding (the exam text of the H&P's
delivery block), plan the discharge teaching, and never use the adult
stable-day pool's rehabilitation wording."""

from __future__ import annotations

import re
from datetime import datetime
from types import SimpleNamespace

import pytest

from clinosim.modules.document.narrative import _delivery
from clinosim.modules.document.narrative.registry import load_document_type_specs
from clinosim.modules.document.narrative.renderers._composers import (
    compose_progress_plan_from_state,
    compose_progress_subjective_from_state,
)
from clinosim.modules.document.narrative.renderers.progress_note import render_progress_note
from clinosim.modules.document.narrative.template_generator import TemplateNarrativeGenerator
from clinosim.types.document import DocumentType
from tests.unit.modules.document.narrative.test_admission_hp_complete_3245 import _delivery_ctx

pytestmark = pytest.mark.unit
_GEN = TemplateNarrativeGenerator()
_ADMIT = datetime(2025, 12, 22, 10, 36)
_BIRTH_START = datetime(2025, 12, 22, 12, 0)
_BIRTH_END = datetime(2025, 12, 22, 12, 30)
_REHAB = re.compile(r"ADL retraining|rehab|自立訓練|リハビリ", re.I)


def _note_ctx(lang: str, day: int, mode: str = "vaginal", los: int = 4, authored: datetime | None = None):
    ctx = _delivery_ctx(lang, "O80" if mode == "vaginal" else "O82")
    ctx.document_type = DocumentType.PROGRESS_NOTE
    ctx.locale = "JP" if lang == "ja" else "US"
    ctx.delivery = {"mode": mode, "gestational_age_days": 282}
    ctx.procedures = [
        SimpleNamespace(
            procedure_type="delivery", encounter_id="ENC-77", start_datetime=_BIRTH_START, end_datetime=_BIRTH_END
        )
    ]
    ctx.day_index = day
    ctx.los_days = los
    ctx.authored_datetime = authored or datetime(2025, 12, 22 + day, 18, 35)
    ctx.vitals = []
    ctx.discharge_disposition = "home"
    ctx.encounter.discharge_disposition = "home"
    return ctx


def test_postpartum_day_counts_from_the_birth() -> None:
    assert _delivery.postpartum_day(_note_ctx("en", 0)) == 0
    assert _delivery.postpartum_day(_note_ctx("en", 2)) == 2
    assert _delivery.postpartum_day(_note_ctx("en", 0, authored=datetime(2025, 12, 22, 11, 0))) is None  # in labor


def test_postpartum_day_of_other_stays_is_none() -> None:
    ctx = _note_ctx("en", 1)
    ctx.delivery = {}
    ctx.diagnoses = [SimpleNamespace(admission_diagnosis_code="I10")]
    assert _delivery.postpartum_day(ctx) is None


@pytest.mark.parametrize("day", [0, 1, 2, 3])
def test_subjective_en_states_the_postpartum_day_not_the_stable_day_pool(day: int) -> None:
    text = compose_progress_subjective_from_state(_note_ctx("en", day))
    assert f"Postpartum day {day}." in text, text
    assert not _REHAB.search(text)
    assert "No new subjective complaints" not in text and "Tolerating initial therapy" not in text


def test_subjective_ja() -> None:
    text = compose_progress_subjective_from_state(_note_ctx("ja", 2))
    assert "産褥2日" in text and not _REHAB.search(text), text


def test_a_note_written_in_labor_says_so() -> None:
    ctx = _note_ctx("en", 0, authored=datetime(2025, 12, 22, 11, 0))
    assert "In labor." in compose_progress_subjective_from_state(ctx)


@pytest.mark.parametrize("lang", ["en", "ja"])
@pytest.mark.parametrize("day", [0, 1, 2])
def test_objective_carries_the_postpartum_finding_every_day(lang: str, day: int) -> None:
    spec = load_document_type_specs()[DocumentType.PROGRESS_NOTE]
    out = render_progress_note(_GEN, _note_ctx(lang, day), spec)
    objective = out.sections["objective"]
    assert ("fundus firm" in objective and "lochia" in objective) if lang == "en" else ("悪露" in objective), objective
    assert not _REHAB.search(out.raw_text), out.raw_text
    assert out.raw_text.count("fundus firm" if lang == "en" else "悪露") == 1
    if lang == "en":
        assert "。" not in out.raw_text, out.raw_text


def test_cesarean_objective_has_the_incision() -> None:
    spec = load_document_type_specs()[DocumentType.PROGRESS_NOTE]
    objective = render_progress_note(_GEN, _note_ctx("en", 1, "cesarean"), spec).sections["objective"]
    assert "incision" in objective


def test_plan_on_the_last_days_has_the_discharge_teaching() -> None:
    last = compose_progress_plan_from_state(_note_ctx("en", 3))
    assert "postpartum warning signs" in last, last
    early = compose_progress_plan_from_state(_note_ctx("en", 1, los=6))
    assert "postpartum warning signs" not in early
    assert "産後の" in compose_progress_plan_from_state(_note_ctx("ja", 3))


def test_non_delivery_progress_notes_are_unchanged() -> None:
    ctx = _note_ctx("en", 1)
    ctx.delivery = {}
    ctx.diagnoses = [SimpleNamespace(admission_diagnosis_code="I10")]
    ctx.procedures = []
    text = compose_progress_subjective_from_state(ctx)
    assert "Postpartum" not in text and "labor" not in text
    spec = load_document_type_specs()[DocumentType.PROGRESS_NOTE]
    assert "fundus" not in render_progress_note(_GEN, ctx, spec).raw_text
