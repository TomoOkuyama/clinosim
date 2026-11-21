"""The referral letter states the hospital course, the discharge prescription
and the significant results, with a purpose consistent with the destination,
and no letter is written for a death (Issue #3268)."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from clinosim.modules.document import engine
from clinosim.modules.document.narrative.renderers.section_builders import jp_clins
from clinosim.modules.document.narrative.template_generator import TemplateNarrativeGenerator
from clinosim.modules.output.fhir_r4.documents.jp_clins.referral_note import _JP_REFERRAL_STRUCTURAL_CHILDREN
from clinosim.types.document import DocumentType, NarrativeContext

pytestmark = pytest.mark.unit


def _ctx(lang: str = "ja", *, rehab: bool = False, meds: bool = True) -> NarrativeContext:
    return NarrativeContext(
        patient=SimpleNamespace(patient_id="P1", sex="male", age=70, chronic_conditions=[]),
        encounter={
            "encounter_id": "ENC-1",
            "admission_datetime": "2026-01-10T10:00:00",
            "discharge_datetime": "2026-01-18T10:00:00",
            "discharge_disposition": "home",
        },
        encounter_type=None,
        disease_protocol=None,
        encounter_protocol=None,
        clinical_course_archetype="",
        severity="moderate",
        day_index=7,
        los_days=8,
        vitals=[],
        lab_results=[],
        medications=[],
        diagnoses=[],
        procedures=[],
        allergies=[],
        rehab_sessions=[{"session_id": "R1"}] if rehab else [],
        document_type=DocumentType.REFERRAL_NOTE,
        target_lang=lang,
        locale="jp" if lang == "ja" else "us",
        authored_datetime=datetime(2026, 1, 18, 10, 0),
        discharge_medications=[
            SimpleNamespace(drug_name="Levofloxacin", dose="500 mg", route="PO", frequency="daily", days_supply=7)
        ]
        if meds
        else [],
    )


@pytest.fixture(scope="module")
def gen() -> TemplateNarrativeGenerator:
    return TemplateNarrativeGenerator()


def test_referral_composition_sections_carry_course_results_and_medications() -> None:
    from clinosim.modules.document.narrative.registry import load_document_type_specs

    sections = list(load_document_type_specs()[DocumentType.REFERRAL_NOTE].composition_sections)
    for name in ("clinical_course_ref", "test_results_ref", "medication_orders_ref"):
        assert name in sections
        assert name in _JP_REFERRAL_STRUCTURAL_CHILDREN


def test_clinical_course_is_the_hospital_course_without_the_results_sentence(gen) -> None:
    text, facts = jp_clins.build_referral_clinical_course(gen, _ctx())
    assert "8" in text and "ctx.los_days" in facts  # the length-of-stay header
    assert "ctx.lab_results" not in facts


def test_medication_orders_name_the_discharge_prescription(gen) -> None:
    text, facts = jp_clins.build_referral_medication_orders(gen, _ctx())
    assert "レボフロキサシン" in text or "Levofloxacin" in text
    assert "ctx.discharge_medications" in facts


def test_medication_orders_without_a_prescription_say_so(gen) -> None:
    text, _ = jp_clins.build_referral_medication_orders(gen, _ctx(meds=False))
    assert text == "退院処方なし"


def test_test_results_without_a_notable_result_say_so(gen) -> None:
    text, facts = jp_clins.build_referral_test_results(gen, _ctx())
    assert "特記すべき異常検査結果の記録なし" in text and facts == []


def test_purpose_follows_the_stay_not_a_hash(gen) -> None:
    for _ in range(3):
        assert "継続加療" in jp_clins.build_referral_purpose(gen, _ctx())[0]
    assert "リハビリテーション継続" in jp_clins.build_referral_purpose(gen, _ctx(rehab=True))[0]


def test_purpose_is_never_a_specialty_referral_within_the_hospital(gen) -> None:
    for rehab in (False, True):
        for lang in ("ja", "en"):
            text = jp_clins.build_referral_purpose(gen, _ctx(lang, rehab=rehab))[0]
            assert "他科紹介" not in text and "specialty" not in text


def test_destination_line_does_not_state_a_purpose(gen) -> None:
    text = jp_clins.build_referral_destination(gen, _ctx())[0]
    assert "継続" not in text and "リハビリ" not in text


def _facts(disposition: str, enc_id: str) -> engine._EncounterFacts:
    return engine._EncounterFacts(
        record=None,
        encounter={"discharge_disposition": disposition},
        encounter_id=enc_id,
        pid="P1",
        admission_dt=datetime(2026, 1, 10),
        discharge_dt=datetime(2026, 1, 18),
        los_days=8,
        config=None,
    )


def test_no_referral_letter_is_planned_for_a_death() -> None:
    assert engine._plan_discharge_referral(None, _facts("snf", "ENC-1"))
    assert engine._plan_discharge_referral(None, _facts("exp", "ENC-1")) == []
