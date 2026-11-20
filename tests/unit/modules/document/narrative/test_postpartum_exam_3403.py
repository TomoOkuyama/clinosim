"""A note of a delivery stay written after the birth states the postpartum
exam, not the antepartum one (Issue #3403)."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from clinosim.modules.document.narrative.renderers.section_builders.patient_history import (
    build_physical_examination,
)
from clinosim.modules.document.narrative.template_generator import TemplateNarrativeGenerator
from clinosim.modules.document.reference_data_loaders import load_disease_exam
from tests.unit.modules.document.narrative.test_admission_hp_complete_3245 import _delivery_ctx

pytestmark = pytest.mark.unit
_GEN = TemplateNarrativeGenerator()
_BIRTH_END = datetime(2025, 12, 22, 12, 6)


def _with_delivery(lang: str, code: str, authored: datetime | None):
    ctx = _delivery_ctx(lang, code)
    ctx.procedures = [
        SimpleNamespace(
            procedure_type="delivery",
            encounter_id="ENC-77",
            start_datetime=datetime(2025, 12, 22, 10, 36),
            end_datetime=_BIRTH_END,
        )
    ]
    ctx.authored_datetime = authored
    return ctx


@pytest.mark.parametrize("code", ["O80", "O82"])
def test_note_after_the_birth_has_the_postpartum_exam(code: str) -> None:
    after = datetime(2025, 12, 22, 14, 0)
    en = build_physical_examination(_GEN, _with_delivery("en", code, after))[0]
    ja = build_physical_examination(_GEN, _with_delivery("ja", code, after))[0]
    assert "fundus firm at or below the umbilicus" in en and "lochia" in en, en
    assert "gravid uterus" not in en and "contractions" not in en
    assert "子宮底は臍高以下" in ja and "悪露" in ja, ja
    assert "妊娠子宮" not in ja and "陣痛" not in ja
    assert ("incision" in en) == (code == "O82")


def test_note_before_the_birth_ended_keeps_the_antepartum_exam() -> None:
    text = build_physical_examination(_GEN, _with_delivery("en", "O80", datetime(2025, 12, 22, 11, 0)))[0]
    assert "gravid uterus" in text and "lochia" not in text


def test_every_mode_has_both_variants_in_both_languages() -> None:
    for exam in load_disease_exam().delivery.modes.values():
        for field in (exam.general_postpartum, exam.obstetric_postpartum):
            assert field["en"] and field["ja"]
