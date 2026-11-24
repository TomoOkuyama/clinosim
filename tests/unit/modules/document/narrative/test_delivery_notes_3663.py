"""Issue #3663: the admission H&P and the discharge summary of a delivery stay
state the obstetric content the record holds (gestational age, how the mother
was admitted, mode, estimated blood loss, complications), and the discharge
instructions are the mother's (postpartum), not the generic adult baseline."""

from __future__ import annotations

import re
from datetime import datetime
from types import SimpleNamespace

import pytest

from clinosim.modules.document.narrative import _delivery
from clinosim.modules.document.narrative.renderers._resolvers import resolve_discharge_instructions
from clinosim.modules.document.narrative.renderers.section_builders.discharge_summary import compose_hospital_course
from clinosim.modules.document.narrative.renderers.section_builders.hpi import build_hpi
from clinosim.modules.document.narrative.renderers.section_builders.patient_history import (
    build_physical_examination,
)
from clinosim.modules.document.narrative.template_generator import TemplateNarrativeGenerator
from clinosim.types.document import DocumentType
from tests.unit.modules.document.narrative.test_admission_hp_complete_3245 import _delivery_ctx

pytestmark = pytest.mark.unit
_GEN = TemplateNarrativeGenerator()
_CJK = re.compile(r"[぀-ヿ㐀-鿿]")
_LATIN_WORDS = re.compile(r"[A-Za-z]{3,}")


def _ctx(lang: str, mode: str = "vaginal", complications: list[str] | None = None, *, doc=DocumentType.ADMISSION_HP):
    ctx = _delivery_ctx(lang, "O80" if mode == "vaginal" else "O82")
    ctx.document_type = doc
    ctx.delivery = {
        "mode": mode,
        "gestational_age_days": 282,
        "estimated_blood_loss_ml": 346,
        "complication_codes": complications or [],
    }
    ctx.locale = "JP" if lang == "ja" else "US"
    return ctx


# ── H&P ───────────────────────────────────────────────────────────────


def test_vaginal_hp_hpi_states_labor_admission_and_gestational_age_en() -> None:
    text = build_hpi(_GEN, _ctx("en"))[0]
    assert "Admitted in labor at 40w2d of gestation." in text, text
    assert "gravida" not in text.lower() and "para" not in text.lower()


def test_cesarean_hp_hpi_en_and_ja() -> None:
    assert "Admitted at 40w2d of gestation for cesarean delivery." in build_hpi(_GEN, _ctx("en", "cesarean"))[0]
    ja = build_hpi(_GEN, _ctx("ja", "cesarean"))[0]
    assert "妊娠40週2日、帝王切開のため入院。" in ja, ja


def test_vaginal_hp_hpi_ja() -> None:
    assert "妊娠40週2日、陣痛のため入院。" in build_hpi(_GEN, _ctx("ja"))[0]


def test_hp_hpi_names_the_complications_of_the_pregnancy() -> None:
    text = build_hpi(_GEN, _ctx("en", complications=["O14.9"]))[0]
    assert "The pregnancy was complicated by Pre-eclampsia." in text, text
    assert "妊娠高血圧腎症" in build_hpi(_GEN, _ctx("ja", complications=["O14.9"]))[0]


def test_hpi_of_a_stay_that_is_not_a_delivery_is_unchanged() -> None:
    ctx = _ctx("en")
    ctx.delivery = {}
    ctx.diagnoses = [SimpleNamespace(admission_diagnosis_code="I10")]
    assert "labor" not in build_hpi(_GEN, ctx)[0]


def test_progress_note_hpi_has_no_admission_sentence() -> None:
    assert "Admitted in labor" not in build_hpi(_GEN, _ctx("en", doc=DocumentType.PROGRESS_NOTE))[0]


@pytest.mark.parametrize("lang", ["en", "ja"])
def test_hp_signed_after_the_birth_still_describes_the_mother_in_labor(lang: str) -> None:
    ctx = _ctx(lang)
    ctx.procedures = [
        SimpleNamespace(
            procedure_type="delivery",
            encounter_id="ENC-77",
            start_datetime=datetime(2025, 12, 22, 10, 36),
            end_datetime=datetime(2025, 12, 22, 12, 6),
        )
    ]
    ctx.authored_datetime = datetime(2025, 12, 22, 13, 0)
    text = build_physical_examination(_GEN, ctx)[0]
    assert ("gravid uterus" in text) if lang == "en" else ("妊娠子宮" in text), text
    assert "lochia" not in text and "悪露" not in text


# ── Discharge summary ─────────────────────────────────────────────────


def test_course_states_mode_gestational_age_blood_loss_and_complications_en() -> None:
    text = compose_hospital_course(_ctx("en", complications=["O42.9"], doc=DocumentType.DISCHARGE_SUMMARY))[0]
    assert "Delivery: vaginal delivery at 40w2d of gestation, estimated blood loss 346 mL." in text, text
    assert "Complications of the pregnancy: Premature rupture of membranes." in text


def test_course_ja() -> None:
    text = compose_hospital_course(_ctx("ja", "cesarean", doc=DocumentType.DISCHARGE_SUMMARY))[0]
    assert "分娩: 帝王切開 (妊娠40週2日)、推定出血量 346 mL。" in text, text


def test_course_without_blood_loss_or_age_states_neither() -> None:
    ctx = _ctx("en", doc=DocumentType.DISCHARGE_SUMMARY)
    ctx.delivery = {"mode": "vaginal"}
    ctx.patient.state_periods = []
    text = compose_hospital_course(ctx)[0]
    assert "Delivery: vaginal delivery." in text and "blood loss" not in text


@pytest.mark.parametrize("lang", ["en", "ja"])
def test_instructions_are_the_mothers(lang: str) -> None:
    entries = resolve_discharge_instructions(_ctx(lang, doc=DocumentType.DISCHARGE_SUMMARY))
    text = " ".join(e[lang] for e in entries.values())
    for generic in ("primary care", "Drink plenty", "十分な水分", "かかりつけ医"):
        assert generic not in text
    assert {"warning_signs", "follow_up", "perineal_care"} <= set(entries)
    assert "incision_care" not in entries
    assert str(_delivery.postpartum_visit_days()) in entries["follow_up"][lang]
    if lang == "en":
        assert not _CJK.search(text)
    else:
        assert not _LATIN_WORDS.search(text.replace("mL", "")), text


def test_cesarean_instructions_have_the_incision_not_the_perineum() -> None:
    entries = resolve_discharge_instructions(_ctx("en", "cesarean", doc=DocumentType.DISCHARGE_SUMMARY))
    assert "incision_care" in entries and "perineal_care" not in entries


def test_adult_discharge_instructions_keep_the_baseline() -> None:
    ctx = _ctx("en", doc=DocumentType.DISCHARGE_SUMMARY)
    ctx.delivery = {}
    ctx.diagnoses = [SimpleNamespace(admission_diagnosis_code="I10")]
    entries = resolve_discharge_instructions(ctx)
    assert "Drink plenty of fluids." in entries["hydrate"]["en"]


def test_delivery_helpers_return_nothing_for_other_stays() -> None:
    ctx = _ctx("en")
    ctx.delivery = {}
    ctx.diagnoses = []
    assert _delivery.delivery_mode(ctx) is None
    assert _delivery.blood_loss_ml(ctx) is None and _delivery.complication_codes(ctx) == []
