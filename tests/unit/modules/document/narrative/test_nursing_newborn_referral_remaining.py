"""Remaining parts of the newborn, nursing and referral document fixes
(Issues #3260, #3267, #3268): the newborn nursing plan and vitamin K record,
the nursing interventions actually provided, ward names, the nursing-history
sentence gap, the category care plan of an admission without a disease
protocol, and the referral letter's imaging, culture, history and remarks."""

from __future__ import annotations

import re
from datetime import datetime
from types import SimpleNamespace

import pytest

from clinosim.modules.document.narrative._narrative_utils import nursing_care_plan_detail
from clinosim.modules.document.narrative.renderers._resolvers import resolve_discharge_instructions
from clinosim.modules.document.narrative.renderers.section_builders import jp_clins
from clinosim.modules.document.narrative.renderers.section_builders.care_plans import build_acp_ward_and_room
from clinosim.modules.document.narrative.renderers.section_builders.discharge_summary import compose_hospital_course
from clinosim.modules.document.narrative.renderers.section_builders.nursing import (
    build_care_plan,
    build_nursing_history,
    build_nursing_interventions_provided,
    build_patient_education,
)
from clinosim.modules.document.narrative.template_generator import TemplateNarrativeGenerator
from clinosim.modules.document.reference_data_loaders import load_nursing_content
from clinosim.types.document import DocumentType, NarrativeContext
from tests.unit.modules.document.narrative.test_newborn_documents_3260 import _ctx as newborn_ctx
from tests.unit.modules.document.narrative.test_referral_letter_3268 import _ctx as referral_ctx

pytestmark = pytest.mark.unit

_CJK = re.compile(r"[぀-ヿ㐀-鿿]")
_VIT_K = SimpleNamespace(
    drug_name="ケイツーシロップ (メナテトレノン 2 mg 経口)",
    drug_id="menatetrenone",
    status="given",
    actual_datetime="2026-01-27T10:00:00",
    dose="2 mg",
    route="PO",
)


@pytest.fixture(scope="module")
def gen() -> TemplateNarrativeGenerator:
    return TemplateNarrativeGenerator()


def _adult(lang: str = "ja", **kw) -> NarrativeContext:
    base = {
        "patient": SimpleNamespace(patient_id="P1", smoking_status="never", sex="male", chronic_conditions=[]),
        "encounter": {"encounter_id": "E1", "admission_datetime": "2026-01-10T10:00:00"},
        "encounter_type": None,
        "disease_protocol": None,
        "encounter_protocol": None,
        "clinical_course_archetype": "",
        "severity": "moderate",
        "day_index": 0,
        "los_days": 5,
        "vitals": [],
        "lab_results": [],
        "medications": [],
        "diagnoses": [],
        "procedures": [],
        "allergies": [],
        "document_type": DocumentType.NURSING_DISCHARGE_SUMMARY,
        "target_lang": lang,
        "locale": "jp" if lang == "ja" else "us",
    }
    base.update(kw)
    return NarrativeContext(**base)


# ── ward names and nursing history ──────────────────────────────────────


@pytest.mark.parametrize(
    ("ward", "bed", "lang", "expected"),
    [
        ("3W", "3W-01", "ja", "病棟：3階西病棟　病室：01号室"),
        ("NBN", "NBN-01", "ja", "病棟：新生児室　病室：01号室"),
        ("3W", "3W-02", "en", "Ward: 3rd floor west ward, Bed: 02"),
        ("NBN", "NBN-01", "en", "Ward: Newborn nursery, Bed: 01"),
    ],
)
def test_ward_and_bed_are_written_as_names(gen, ward, bed, lang, expected) -> None:
    ctx = SimpleNamespace(encounter={"ward_id": ward, "bed_number": bed}, target_lang=lang)
    assert build_acp_ward_and_room(gen, ctx)[0] == expected


def test_every_configured_ward_has_a_name() -> None:
    import yaml

    from clinosim.locale.loader import vocab_display

    for cfg in ("hospital_operations", "hospital_large", "hospital_small"):
        data = yaml.safe_load(open(f"clinosim/config/{cfg}.yaml"))
        for ward in {w for ws in data["wards"].values() for w in ws if not w.startswith("OPD")}:
            for lang in ("ja", "en"):
                name = vocab_display("ward_name", ward, lang) or vocab_display("care_location", ward, lang)
                assert name, (cfg, ward, lang)


def test_us_nursing_history_separates_sentences(gen) -> None:
    ctx = _adult(
        "en",
        patient=SimpleNamespace(patient_id="P1", sex="male", chronic_conditions=[SimpleNamespace(code="N18.9")]),
        allergies=[SimpleNamespace(allergen="Aspirin", substance="Aspirin", display="Aspirin")],
    )
    text, _ = build_nursing_history(gen, ctx)
    assert not re.search(r"\.[A-Z]", text), text


# ── nursing interventions provided ──────────────────────────────────────


def test_interventions_come_from_the_care_given_not_only_io_totals(gen) -> None:
    ctx = _adult(
        "ja",
        medications=[
            SimpleNamespace(drug_name="Ceftriaxone", status="given"),
            SimpleNamespace(drug_name="Ceftriaxone", status="given"),
            SimpleNamespace(drug_name="Acetaminophen", status="held"),
        ],
        vitals=[SimpleNamespace(on_supplemental_oxygen=True), SimpleNamespace(on_supplemental_oxygen=False)],
        rehab_sessions=[object(), object()],
        nursing_risk_assessments=[SimpleNamespace(fall_risk_level="high", braden_total=12)],
        intake_output_records=[
            SimpleNamespace(
                intake_iv_ml=500,
                intake_oral_ml=300,
                intake_other_ml=0,
                output_urine_ml=600,
                output_drain_ml=0,
                output_other_ml=0,
            )
        ],
        disease_protocol=SimpleNamespace(disease_id="urinary_tract_infection"),
    )
    text, facts = build_nursing_interventions_provided(gen, ctx)
    for part in (
        "与薬 2 回 (薬剤 1 種類)",
        "バイタルサイン測定 2 回",
        "酸素投与下の観察 1 回",
        "リハビリテーション 2 回",
    ):
        assert part in text, part
    assert "転倒予防策" in text and "褥瘡予防" in text and "IN 800 mL" in text and "指導:" in text
    assert {"ctx.medications", "ctx.vitals", "ctx.rehab_sessions", "ctx.nursing_risk_assessments"} <= set(facts)


def test_interventions_without_any_record_keep_the_fallback(gen) -> None:
    text, facts = build_nursing_interventions_provided(gen, _adult("en"))
    assert facts == [] and "no significant findings" in text


def test_no_education_is_claimed_for_a_death(gen) -> None:
    ctx = _adult(
        "ja",
        disease_protocol=SimpleNamespace(disease_id="sepsis"),
        encounter={"encounter_id": "E1", "admission_datetime": "2026-01-10T10:00:00", "discharge_disposition": "exp"},
        vitals=[SimpleNamespace(on_supplemental_oxygen=False)],
    )
    assert "指導:" not in build_nursing_interventions_provided(gen, ctx)[0]


# ── care plan of an admission without a disease protocol ─────────────────


@pytest.mark.parametrize(
    ("code", "problem"),
    [
        ("I21.9", "心拍出量減少のリスク"),
        ("I63.9", "神経学的変化のリスク"),
        ("O80", "産褥期の子宮復古・出血のリスク"),
        ("R53.1", "原因精査中の症状 (倦怠感・疼痛など)"),
        ("S72.0", "急性疼痛 (外傷部)"),
        ("N10", "排尿障害"),
        ("J18.9", "ガス交換障害"),
    ],
)
def test_category_care_plan_follows_the_admission_diagnosis(gen, code, problem) -> None:
    ctx = _adult(
        "ja",
        document_type=DocumentType.ADMISSION_NURSING_ASSESSMENT,
        diagnoses=[SimpleNamespace(admission_diagnosis_code=code)],
    )
    plan, facts = build_care_plan(gen, ctx)
    assert f"看護問題「{problem}」" in plan and "目標:" in plan, plan
    assert facts[0] == "ctx.diagnoses"


def test_without_a_known_category_the_generic_text_stays(gen) -> None:
    ctx = _adult("en", diagnoses=[SimpleNamespace(admission_diagnosis_code="Z99.9")])
    assert build_care_plan(gen, ctx)[0] == "Care plan: continue standard nursing care"


def test_every_category_prefix_is_valid_and_the_entries_are_complete() -> None:
    categories = load_nursing_content()["diagnosis_category"]
    for key, entry in categories.items():
        assert entry["icd10_prefixes"] and entry["care_plan_detail"]["goal"]["ja"], key
    prefixes = [p for e in categories.values() for p in e["icd10_prefixes"]]
    assert len(prefixes) == len(set(prefixes))


def test_a_never_smoker_is_not_taught_cessation_in_a_category_plan(gen) -> None:
    ctx = _adult("ja", diagnoses=[SimpleNamespace(admission_diagnosis_code="J18.9")])
    assert "禁煙" not in build_patient_education(gen, ctx)[0]


# ── newborn nursing and vitamin K ───────────────────────────────────────


@pytest.mark.parametrize("lang", ["ja", "en"])
def test_newborn_nursing_plan_is_neonatal(gen, lang) -> None:
    ctx = newborn_ctx(lang)
    plan, facts = build_care_plan(gen, ctx)
    edu, _ = build_patient_education(gen, ctx)
    assert nursing_care_plan_detail(ctx, lang)["problem"]
    assert facts[0] == "ctx.patient.date_of_birth"
    assert ("看護問題" in plan and "哺乳" in plan) if lang == "ja" else ("feeding" in plan and "Goal:" in plan)
    assert ("授乳" in edu) if lang == "ja" else ("feeding" in edu)
    if lang == "en":
        assert not _CJK.search(plan + edu)


def test_newborn_nursing_discharge_interventions_name_the_recorded_doses_and_screens(gen) -> None:
    ctx = newborn_ctx("ja")
    ctx.medications = [_VIT_K]
    ctx.procedures = [SimpleNamespace(procedure_name="AABR", procedure_type="hearing_screen_aabr")]
    ctx.document_type = DocumentType.NURSING_DISCHARGE_SUMMARY
    text, _ = build_nursing_interventions_provided(gen, ctx)
    assert "新生児への投与: " in text and "ケイツー" in text and "指導:" in text


def test_hospital_course_states_only_the_recorded_newborn_dose(gen) -> None:
    ctx = newborn_ctx("ja", dob="2026-01-26", admitted="2026-01-26T10:09:00")
    ctx.medications = [_VIT_K]
    ctx.authored_datetime = datetime(2026, 1, 31, 10, 0)
    text, _ = compose_hospital_course(ctx)
    assert "新生児への投与: メナテトレノン (日齢1)。" in text
    assert "1 か月" not in text and "1週間" not in text


def test_newborn_vitamin_k_instruction_only_when_a_dose_is_recorded() -> None:
    with_k = newborn_ctx("ja")
    with_k.newborn_workup = {**with_k.newborn_workup, "has_vitamin_k": True}
    assert "vitamin_k" in resolve_discharge_instructions(with_k)
    assert "vitamin_k" not in resolve_discharge_instructions(newborn_ctx("ja"))
    en = resolve_discharge_instructions(with_k)["vitamin_k"]["en"]
    assert "vitamin K" in en and "further dose" in en


# ── referral letter results, history, remarks ───────────────────────────


def _study() -> SimpleNamespace:
    return SimpleNamespace(
        description="CT_head_noncontrast",
        report={
            "impression_text": "No acute intracranial abnormality.",
            "impression_text_ja": "急性頭蓋内異常を認めず。",
        },
    )


def _culture(growth: bool = True) -> SimpleNamespace:
    return SimpleNamespace(
        specimen="blood",
        specimen_snomed="119297000",
        growth=growth,
        organism_snomed="9861002" if growth else "",
        susceptibilities=[
            SimpleNamespace(antibiotic_loinc="18864-9", interpretation="I"),
            SimpleNamespace(antibiotic_loinc="18895-3", interpretation="S"),
        ]
        if growth
        else [],
    )


def test_referral_results_carry_imaging_impressions_and_cultures(gen) -> None:
    ctx = referral_ctx("ja")
    ctx.imaging_studies = [_study()]
    ctx.microbiology = [_culture(), _culture(growth=False)]
    text, facts = jp_clins.build_referral_test_results(gen, ctx)
    assert "画像検査: 頭部 CT (単純): 急性頭蓋内異常を認めず。" in text
    assert "血液培養で肺炎球菌を検出 (感受性: アンピシリン I、セフトリアキソン S)" in text
    assert "血液培養は発育なし" in text
    assert {"ctx.imaging_studies", "ctx.microbiology"} <= set(facts)


def test_referral_results_in_english_have_no_japanese(gen) -> None:
    ctx = referral_ctx("en")
    ctx.imaging_studies = [_study()]
    ctx.microbiology = [_culture()]
    text, _ = jp_clins.build_referral_test_results(gen, ctx)
    assert "Imaging: CT head (non-contrast): No acute intracranial abnormality" in text
    assert "Blood culture grew Streptococcus pneumoniae (susceptibility: Ampicillin I, cefTRIAXone S)" in text
    assert not _CJK.search(text)


def test_referral_results_without_any_record_say_so(gen) -> None:
    assert "特記すべき異常検査結果の記録なし" in jp_clins.build_referral_test_results(gen, referral_ctx())[0]


def test_referral_history_sections_reuse_the_history_builders(gen) -> None:
    ctx = referral_ctx("ja")
    past, _ = jp_clins.build_referral_past_history(gen, ctx)
    family, _ = jp_clins.build_referral_family_history(gen, ctx)
    assert past == "特記既往歴なし"
    assert family


def test_referral_remarks_state_allergies_and_code_status_or_none(gen) -> None:
    ctx = referral_ctx("ja")
    text, _ = jp_clins.build_referral_remarks(gen, ctx)
    assert "コードステータス" not in text and text
    ctx.code_status = "304253006"
    ctx.allergies = []
    assert "コードステータス: " in jp_clins.build_referral_remarks(gen, ctx)[0]


def test_referral_composition_emits_history_and_remarks_sections() -> None:
    from clinosim.modules.output.fhir_r4.documents.composition import _build_composition

    sections = {
        "referring_institution": "当院",
        "referral_destination": "他院",
        "referral_purpose": "継続加療のため。",
        "diagnoses_and_complaint": "1. 肺炎",
        "present_illness_ref": "受診。",
        "past_history_ref": "特記既往歴なし",
        "family_history_ref": "特記家族歴なし",
        "clinical_course_ref": "入院 8 日間。",
        "test_results_ref": "異常なし。",
        "medication_orders_ref": "退院処方なし",
        "remarks_ref": "アレルギーなし",
    }
    doc = {
        "document_id": "doc-1",
        "patient_id": "P1",
        "encounter_id": "E1",
        "task_type": "referral_note",
        "loinc_code": "57133-1",
        "authored_datetime": "2026-01-18T10:00:00",
        "narrative": {"sections": sections},
    }
    comp = _build_composition(doc, sections, "ja", country="JP")
    top = [s["code"]["coding"][0]["code"] for s in comp["section"]]
    assert top == ["920", "910", "300", "220"]
    children = [c["code"]["coding"][0]["code"] for c in comp["section"][2]["section"]]
    assert children == ["950", "340", "360", "370", "550", "330", "620", "430"]
