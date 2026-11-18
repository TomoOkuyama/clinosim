"""The nursing care plan, diagnoses and education address the admission problem
(Issue #3267): every simulated disease has an acute entry with a goal and OP /
TP / EP interventions, a comorbidity's own disease problems are not read as
problems of the admission, and cessation teaching goes to smokers only."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from clinosim.modules.document.narrative._narrative_utils import _lookup_nursing_content
from clinosim.modules.document.narrative.renderers.section_builders.nursing import (
    build_care_plan,
    build_nursing_diagnosis,
    build_patient_education,
)
from clinosim.modules.document.narrative.template_generator import TemplateNarrativeGenerator
from clinosim.modules.document.reference_data_loaders import load_nursing_content
from clinosim.types.document import DocumentType, NarrativeContext

pytestmark = pytest.mark.unit

_DISEASE_DIR = Path(__file__).resolve().parents[4].parent / "clinosim" / "modules" / "disease" / "reference_data"


def _ctx(disease: str, lang: str = "ja", chronic: tuple[str, ...] = (), smoking: str = "never") -> NarrativeContext:
    return NarrativeContext(
        patient=SimpleNamespace(
            patient_id="P1",
            smoking_status=smoking,
            chronic_conditions=[SimpleNamespace(code=c) for c in chronic],
        ),
        encounter={"encounter_id": "E1", "admission_datetime": "2026-01-10T10:00:00"},
        encounter_type=None,
        disease_protocol=SimpleNamespace(disease_id=disease),
        encounter_protocol=None,
        clinical_course_archetype="",
        severity="moderate",
        day_index=0,
        los_days=5,
        vitals=[],
        lab_results=[],
        medications=[],
        diagnoses=[],
        procedures=[],
        allergies=[],
        document_type=DocumentType.ADMISSION_NURSING_ASSESSMENT,
        target_lang=lang,
        locale="jp" if lang == "ja" else "us",
    )


@pytest.fixture(scope="module")
def gen() -> TemplateNarrativeGenerator:
    return TemplateNarrativeGenerator()


def test_every_simulated_disease_has_an_acute_entry_with_a_care_plan_detail() -> None:
    acute = load_nursing_content()["acute_disease"]
    diseases = {p.stem for p in _DISEASE_DIR.glob("*.yaml")}
    assert diseases, _DISEASE_DIR
    assert diseases <= set(acute), sorted(diseases - set(acute))
    for disease in diseases:
        assert acute[disease].get("care_plan_detail"), disease


def test_ami_plans_pain_and_cardiac_output_not_bp_control(gen) -> None:
    ctx = _ctx("acute_mi", chronic=("I10", "E11"))
    dx, _ = build_nursing_diagnosis(gen, ctx)
    plan, facts = build_care_plan(gen, ctx)
    assert "胸痛" in dx and "心拍出量減少" in dx
    assert "血圧管理不足" not in dx
    assert "看護問題「急性疼痛 (胸痛)」" in plan and "目標:" in plan
    assert "観察計画 (OP):" in plan and "ケア計画 (TP):" in plan and "教育計画 (EP):" in plan
    assert "血圧を朝夕測定" not in plan
    assert "ctx.disease_protocol.disease_id" in facts


def test_en_care_plan_is_english_and_structured(gen) -> None:
    plan, _ = build_care_plan(gen, _ctx("acute_mi", "en"))
    assert plan.startswith("Care plan: Nursing problem: acute pain (chest pain). Goal: ")
    assert "Observation:" in plan and "Care:" in plan and "Education:" in plan
    assert not any("぀" <= ch <= "鿿" for ch in plan)


def test_uti_of_a_copd_patient_has_no_gas_exchange_or_cessation_teaching(gen) -> None:
    ctx = _ctx("urinary_tract_infection", chronic=("J44",), smoking="never")
    dx, _ = build_nursing_diagnosis(gen, ctx)
    plan, _ = build_care_plan(gen, ctx)
    edu, _ = build_patient_education(gen, ctx)
    assert "ガス交換" not in dx + plan
    assert "酸素" not in plan
    assert "禁煙" not in edu and "呼吸リハビリ" not in edu
    assert "感染" in dx and "排尿" in dx


def test_cessation_teaching_goes_to_a_smoker_only() -> None:
    never, _ = _lookup_nursing_content(_ctx("copd_exacerbation", smoking="never"), "patient_education", "ja", 8)
    former, _ = _lookup_nursing_content(_ctx("copd_exacerbation", smoking="former"), "patient_education", "ja", 8)
    assert not any("禁煙" in x for x in never)
    assert any("禁煙" in x for x in former)


def test_comorbidity_monitoring_that_applies_to_any_stay_is_kept(gen) -> None:
    ctx = _ctx("urinary_tract_infection", chronic=("E11",))
    plan, facts = build_care_plan(gen, ctx)
    assert "併存疾患・リスクへの対応:" in plan and "血糖モニタ" in plan
    assert "ctx.patient.chronic_conditions" in facts


def test_chronic_only_path_is_unchanged_without_an_acute_entry() -> None:
    ctx = _ctx("not_a_disease", chronic=("I10", "J44"), smoking="never")
    dx, _ = _lookup_nursing_content(ctx, "nursing_diagnoses", "en", 5)
    assert dx == ["risk for inadequate BP control", "risk for impaired gas exchange"]
    edu, _ = _lookup_nursing_content(ctx, "patient_education", "en", 5)
    assert "smoking cessation" not in edu


@pytest.mark.parametrize("lang", ["ja", "en"])
def test_no_double_punctuation_in_any_disease_plan(gen, lang) -> None:
    for disease in load_nursing_content()["acute_disease"]:
        plan, _ = build_care_plan(gen, _ctx(disease, lang))
        assert "。。" not in plan and ".." not in plan, disease
