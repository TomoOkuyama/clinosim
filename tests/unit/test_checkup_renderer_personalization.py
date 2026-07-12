"""P2-13 PR3 sub-PR-B:JP-eCheckup section renderer 個別化 unit tests(JP-only)."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from clinosim.modules.document.narrative.template_generator import (
    TemplateNarrativeGenerator,
)


def _make_lab_result(loinc: str, value):
    """OrderResult-shape dict(_o dual-access に耐える)。"""
    return SimpleNamespace(
        result_datetime=datetime(2026, 4, 15, 10, 0, 0),
        performed_by="",
        lab_name=loinc,
        value=value,
        unit=None,
        reference_range=None,
        flag=None,
        interpretation="N",
        specimen_note=None,
    )


def _make_ctx(lab_results, patient):
    """narrative context 最小構成。"""
    from clinosim.modules.document.narrative.registry import load_document_type_specs
    from clinosim.types.document import DocumentType, NarrativeContext
    ctx = NarrativeContext(
        patient=patient,
        encounter=SimpleNamespace(encounter_id="CHK-ENC-001", admission_datetime="2026-04-15T09:00:00"),
        encounter_type=None,
        disease_protocol=None,
        encounter_protocol=None,
        clinical_course_archetype="",
        severity="",
        day_index=0,
        los_days=1,
        vitals=[],
        lab_results=lab_results,
        medications=[],
        diagnoses=[],
        procedures=[],
        allergies=[],
        document_type=DocumentType("health_checkup_report"),
        target_lang="ja",
        locale="jp",
    )
    return ctx


@pytest.mark.unit
def test_checkup_lab_results_all_normal_grade_a():
    """全項目が基準内 → 総合判定 A(異常なし)。"""
    gen = TemplateNarrativeGenerator()
    labs = [
        _make_lab_result("39156-5", 22.5),   # BMI 標準
        _make_lab_result("8480-6", 118),      # 収縮期 BP 基準内
        _make_lab_result("8462-4", 76),       # 拡張期 BP 基準内
        _make_lab_result("4548-4", 5.4),      # HbA1c 基準内
        _make_lab_result("18262-6", 100),     # LDL 基準内
    ]
    ctx = _make_ctx(labs, patient=SimpleNamespace(patient_id="P1"))
    text, facts = gen._build_checkup_lab_results(ctx)
    assert "総合判定:A" in text
    assert "異常なし" in text
    assert "22.5" in text
    assert "118/76" in text
    assert "5.4%" in text


@pytest.mark.unit
def test_checkup_lab_results_high_bp_grade_d():
    """収縮期 BP 140 以上 → 高血圧、総合判定 D。"""
    gen = TemplateNarrativeGenerator()
    labs = [
        _make_lab_result("39156-5", 24.0),
        _make_lab_result("8480-6", 152),      # 高血圧
        _make_lab_result("8462-4", 96),
        _make_lab_result("4548-4", 5.4),
        _make_lab_result("18262-6", 100),
    ]
    ctx = _make_ctx(labs, patient=SimpleNamespace(patient_id="P2"))
    text, _ = gen._build_checkup_lab_results(ctx)
    assert "高血圧" in text
    assert "総合判定:D" in text


@pytest.mark.unit
def test_checkup_lab_results_high_hba1c_grade_d():
    """HbA1c 6.5 以上 → 糖尿病型、総合判定 D。"""
    gen = TemplateNarrativeGenerator()
    labs = [
        _make_lab_result("39156-5", 25.0),
        _make_lab_result("8480-6", 128),
        _make_lab_result("8462-4", 82),
        _make_lab_result("4548-4", 7.2),      # 糖尿病型
        _make_lab_result("18262-6", 100),
    ]
    ctx = _make_ctx(labs, patient=SimpleNamespace(patient_id="P3"))
    text, _ = gen._build_checkup_lab_results(ctx)
    assert "糖尿病型" in text
    assert "総合判定:D" in text


@pytest.mark.unit
def test_checkup_lab_results_missing_values_default_to_normal():
    """空の lab_results では未測定表記になり、総合判定 A(異常なし)。"""
    gen = TemplateNarrativeGenerator()
    ctx = _make_ctx([], patient=SimpleNamespace(patient_id="P4"))
    text, _ = gen._build_checkup_lab_results(ctx)
    assert "未測定" in text
    assert "総合判定:A" in text


@pytest.mark.unit
def test_checkup_questionnaire_healthy_patient():
    """慢性疾患なし・喫煙なし・飲酒なしの健康患者は経過観察不要。"""
    gen = TemplateNarrativeGenerator()
    patient = SimpleNamespace(
        patient_id="P5",
        chronic_conditions=[],
        current_medications=[],
        smoking_status="never",
        alcohol_use="none",
    )
    ctx = _make_ctx([], patient=patient)
    text, _ = gen._build_checkup_questionnaire(ctx)
    assert "経過観察不要" in text
    assert "喫煙歴なし" in text
    assert "飲酒なし" in text
    assert "常用薬なし" in text


@pytest.mark.unit
def test_checkup_questionnaire_patient_with_chronic_conditions():
    """慢性疾患保有時は経過観察を要す。"""
    from clinosim.types.patient import ChronicCondition
    gen = TemplateNarrativeGenerator()
    patient = SimpleNamespace(
        patient_id="P6",
        chronic_conditions=[
            ChronicCondition(code="I10", system="icd-10", severity="mild"),
        ],
        current_medications=["アムロジピン 5mg"],
        smoking_status="former",
        alcohol_use="regular",
    )
    ctx = _make_ctx([], patient=patient)
    text, _ = gen._build_checkup_questionnaire(ctx)
    assert "継続経過観察を要す" in text
    assert "アムロジピン" in text
    assert "禁煙" in text
    assert "習慣的飲酒" in text
    # I10 の日本語 display が resolve されていること(codes/data/icd-10.yaml)
    assert "I10" in text
