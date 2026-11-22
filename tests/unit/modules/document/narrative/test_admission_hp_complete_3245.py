"""The rest of the admission H&P (Issues #3245, #3241): the day-0 note after
the H&P, the delivery and mixed-diagnosis exams, the newborn's birth data and
screening results, and the plan from the admission orders."""

from __future__ import annotations

from datetime import date, datetime
from types import SimpleNamespace

import pytest

from clinosim.modules.document.narrative.context import newborn_workup_known_at
from clinosim.modules.document.narrative.renderers._composers import newborn_screening_to_date
from clinosim.modules.document.narrative.renderers.section_builders.assessment_and_plan import (
    admission_order_items,
    build_assessment_and_plan,
)
from clinosim.modules.document.narrative.renderers.section_builders.patient_history import (
    build_physical_examination,
    build_social_history,
)
from clinosim.modules.document.narrative.template_generator import TemplateNarrativeGenerator
from clinosim.simulator.perinatal import _birth_data
from clinosim.types.document import DocumentType, NarrativeContext
from clinosim.types.patient import ChronicCondition, PatientProfile, TemporalStatePeriod
from tests.unit.modules.document.narrative.test_admission_hp_exam_3245 import _ADMIT, _ctx, _vital

pytestmark = pytest.mark.unit
_GEN = TemplateNarrativeGenerator()


def _preg(lmp: str = "2025-03-21") -> list[TemporalStatePeriod]:
    return [
        TemporalStatePeriod(
            state_type="pregnancy",
            start_date=date.fromisoformat(lmp),
            end_date=date(2025, 12, 31),
            outcome="delivered",
            metadata={"lmp": lmp, "edd": "2025-12-26"},
        )
    ]


def test_day0_progress_note_is_authored_after_the_hp() -> None:
    from clinosim.modules.document.engine import _EncounterFacts, _plan_admission_once, _plan_daily
    from clinosim.modules.document.narrative.registry import load_document_type_specs

    specs = load_document_type_specs()
    facts = _EncounterFacts(
        record=None,
        encounter=None,
        encounter_id="E",
        pid="P",
        admission_dt=_ADMIT,
        discharge_dt=datetime(2025, 11, 25, 10, 0),
        los_days=3,
        config=None,
    )
    hp = _plan_admission_once(specs[DocumentType.ADMISSION_HP], facts)[0]
    notes = _plan_daily(specs[DocumentType.PROGRESS_NOTE], facts)
    assert notes[0].authored > hp.authored
    assert notes[0].period_start == _ADMIT.isoformat()
    assert [n.authored for n in notes[1:]] == ["2025-11-21T18:35:00", "2025-11-22T18:35:00"]
    # another daily spec keeps the admission time
    assert _plan_daily(specs[DocumentType.NURSING_SHIFT_NOTE], facts)[0].authored == _ADMIT.isoformat()


def _delivery_ctx(lang: str, code: str, *, with_lmp: bool = True) -> NarrativeContext:
    ctx = _ctx(None, lang, severity="", vitals=[_vital(_ADMIT)])
    ctx.diagnoses = [SimpleNamespace(admission_diagnosis_code=code)]
    ctx.patient.state_periods = _preg() if with_lmp else []
    ctx.encounter.admission_datetime = datetime(2025, 12, 22, 10, 36)
    return ctx


def test_delivery_admission_has_an_obstetric_exam_with_the_gestational_age() -> None:
    text = build_physical_examination(_GEN, _delivery_ctx("en", "O80"))[0]
    assert (
        "Obstetric: gravid uterus, fundal height consistent with 39w3d gestation, uterine contractions palpable" in text
    ), text
    assert "no additional exam findings" not in text
    ja = build_physical_examination(_GEN, _delivery_ctx("ja", "O80"))[0]
    assert "産科: 妊娠子宮を触知し、子宮底長は在胎 39 週 3 日相当、子宮収縮を触知する" in ja and "項部硬直" not in ja, (
        ja
    )


def test_cesarean_admission_does_not_assert_contractions_and_needs_no_lmp() -> None:
    cesarean = build_physical_examination(_GEN, _delivery_ctx("en", "O82"))[0]
    assert "39w3d gestation" in cesarean and "contractions" not in cesarean, cesarean
    assert "Obstetric: gravid uterus" in build_physical_examination(_GEN, _delivery_ctx("en", "O82", with_lmp=False))[0]


def test_mixed_diagnosis_admission_has_the_exam_of_the_principal_disease() -> None:
    ctx = _ctx(None, "en", severity="severe", vitals=[_vital(_ADMIT, heart_rate=130, systolic_bp=80)])
    ctx.principal_disease_id = "sepsis"
    text = build_physical_examination(_GEN, ctx)[0]
    assert "tachycardia, hypotension, delayed capillary refill" in text, text
    assert "no additional exam findings" not in text


def test_birth_data_comes_from_the_mothers_record() -> None:
    mother = PatientProfile(patient_id="M", sex="F", date_of_birth=date(1990, 1, 1))
    mother.age = 35
    mother.state_periods = _preg()
    mother.chronic_conditions = [ChronicCondition(code="E66.9")]
    data = _birth_data(mother, datetime(2025, 12, 22, 10, 36), cesarean=True)
    assert data == {
        "gestational_age_days": 276,
        "delivery_mode": "cesarean",
        "maternal_age": 35,
        "maternal_condition_codes": ["E66.9"],
    }
    assert _birth_data(PatientProfile(patient_id="N"), datetime(2025, 12, 22), False)["gestational_age_days"] is None


def _baby(lang: str, birth: dict | None) -> NarrativeContext:
    ctx = _ctx(None, lang, vitals=[])
    ctx.patient = PatientProfile(patient_id="M-BABY", sex="F", date_of_birth=date(2025, 12, 22))
    ctx.patient.age = 0
    ctx.patient.occupation = "infant"
    ctx.patient.weight_kg, ctx.patient.height_cm = 3.2, 50.0
    ctx.encounter = {"encounter_id": "ENC-B", "admission_datetime": "2025-12-22T10:36:00", "admit_source": "born"}
    ctx.newborn_workup = {
        "is_neonate": True,
        "apgar_1min": 8,
        "apgar_5min": 9,
        "birth": birth if birth is not None else {},
        "birth_weight_kg": 3.2,
        "birth_length_cm": 50.0,
        "bilirubin_series": [{"timestamp": "2025-12-23T10:00:00", "day": 1, "value_mg_dl": 6.2}],
        "has_aabr": True,
        "aabr_outcome_key": "pass",
        "event_times": {"aabr": "2025-12-23T10:36:00"},
    }
    return ctx


def test_newborn_birth_history_lists_the_birth_data_the_record_holds() -> None:
    birth = {
        "gestational_age_days": 276,
        "delivery_mode": "cesarean",
        "maternal_age": 35,
        "maternal_condition_codes": ["E66.9"],
    }
    en = build_social_history(_GEN, _baby("en", birth))[0]
    assert "gestational age 39w3d" in en and "cesarean delivery" in en, en
    assert "birth weight 3.2 kg" in en and "birth length 50 cm" in en and "Maternal history: maternal age 35" in en, en
    ja = build_social_history(_GEN, _baby("ja", birth))[0]
    assert (
        "在胎 39 週 3 日" in ja and "帝王切開分娩" in ja and "出生体重 3.2 kg" in ja and "母体歴: 母体年齢 35 歳" in ja
    ), ja


def test_newborn_without_any_birth_data_says_so() -> None:
    ctx = _baby("en", None)
    ctx.newborn_workup["birth_weight_kg"] = ctx.newborn_workup["birth_length_cm"] = None
    assert "birth data not recorded" in build_social_history(_GEN, ctx)[0]


def test_newborn_screening_is_cited_by_the_notes_after_it_resulted() -> None:
    ctx = _baby("en", {})
    ctx.authored_datetime = datetime(2025, 12, 22, 12, 0)
    assert newborn_screening_to_date(ctx) == ""
    ctx.authored_datetime = datetime(2025, 12, 24, 12, 0)
    text = newborn_screening_to_date(ctx)
    assert "AABR hearing screen: pass" in text and "bilirubin" not in text and "Apgar" not in text, text
    with_bili = newborn_screening_to_date(ctx, with_bilirubin=True)
    assert "last transcutaneous bilirubin 6.2 mg/dL (day of life 1)" in with_bili, with_bili
    assert newborn_workup_known_at(ctx.newborn_workup, ctx.authored_datetime)["has_aabr"]
    assert newborn_screening_to_date(_ctx("acute_mi", "en")) == ""


def _order(order_set: str, kind: str, name: str, panel: str = "") -> SimpleNamespace:
    return SimpleNamespace(
        order_set=order_set, order_type=kind, display_name=name, panel_key=panel, encounter_id="ENC-77"
    )


def test_plan_lists_the_admission_work_up_and_supportive_care_from_the_orders() -> None:
    ctx = _ctx("cerebral_infarction", "en")
    ctx.orders = [
        _order("admission_initial", "lab", "WBC", "CBC"),
        _order("admission_initial", "lab", "Hb", "CBC"),
        _order("admission_initial", "imaging", "CT_head_noncontrast"),
        _order("admission_initial", "therapy", "neuro_checks: NIHSS q2h for first 24h, then q4h"),
        _order("admission_care", "therapy", "HOB_elevation: Head of bed flat 30 degrees per protocol"),
        _order("", "lab", "Creatinine"),  # a later order is not the admission's
    ]
    items = admission_order_items(ctx)
    assert items[0].startswith("Admission work-up: CBC") and "Creatinine" not in items[0], items
    assert items[1].startswith("Supportive care and monitoring: ") and "NIHSS" in items[1], items
    plan = build_assessment_and_plan(_GEN, ctx)[0]
    assert "Admission work-up" in plan and "Supportive care and monitoring" in plan, plan
    ja = _ctx("cerebral_infarction", "ja")
    ja.orders = ctx.orders
    assert admission_order_items(ja)[0].startswith("入院時検査: ")


def test_admission_without_a_diagnosis_has_the_general_appearance_only() -> None:
    ctx = _ctx(None, "ja", vitals=[_vital(_ADMIT)])
    text = build_physical_examination(_GEN, ctx)[0]
    assert "一般状態: 意識清明、中等度の苦痛様" in text, text
    assert "項部硬直" not in text and "麻痺なし" not in text and "循環器" not in text, text
