"""Tests for neonatal admission_hp narrative wiring (Issue #1404).

Covers:
- ``context._build_newborn_workup`` projection from
  ``record.extensions["newborn"]`` + top-level procedures / MARs.
- Non-neonate records return empty dict (gate).
- ``replacement_strategy._render_newborn_workup_summary`` locale-aware
  rendering (JA + EN) with all fields, and with missing fields.
- ``_build_extra_context`` emits ``newborn_workup_summary`` only for
  admission_hp doc-type on a neonate ctx.
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

from clinosim.modules.document.narrative.context import _build_newborn_workup
from clinosim.modules.document.narrative.replacement_strategy import (
    _build_extra_context,
    _render_newborn_workup_summary,
)
from clinosim.types.document import DocumentType

# ---------------------------------------------------------------------------
# _build_newborn_workup
# ---------------------------------------------------------------------------


def _neonate_patient() -> SimpleNamespace:
    return SimpleNamespace(
        patient_id="pt-newborn-1",
        age=0,
        occupation="infant",
        chronic_conditions=[],
    )


def _adult_patient() -> SimpleNamespace:
    return SimpleNamespace(
        patient_id="pt-adult-1",
        age=42,
        occupation="engineer",
        chronic_conditions=[],
    )


def _neonate_record() -> SimpleNamespace:
    return SimpleNamespace(
        patient=_neonate_patient(),
        extensions={
            "newborn": {
                "apgar": [
                    {"minute": 1, "score": 8, "timestamp": datetime(2026, 7, 1, 10, 1)},
                    {"minute": 5, "score": 9, "timestamp": datetime(2026, 7, 1, 10, 5)},
                ],
                "bilirubin": [
                    {"total_bilirubin_mg_dl": 8.2, "timestamp": datetime(2026, 7, 2)},
                    {"total_bilirubin_mg_dl": 11.4, "timestamp": datetime(2026, 7, 3)},
                    {"total_bilirubin_mg_dl": 9.5, "timestamp": datetime(2026, 7, 4)},
                ],
                "cchd_pulse_ox": [
                    {"site": "RU", "spo2_percent": 98},
                    {"site": "LE", "spo2_percent": 97},
                ],
            }
        },
        procedures=[
            SimpleNamespace(display_name="AABR hearing screen"),
            SimpleNamespace(display_name="Tandem-MS metabolic screen"),
        ],
        medication_administrations=[
            SimpleNamespace(medication_display_name="Vitamin K 1 mg PO", route="PO"),
            SimpleNamespace(medication_display_name="Erythromycin ophthalmic ointment", route="OPH"),
        ],
    )


def test_build_newborn_workup_full() -> None:
    record = _neonate_record()
    wu = _build_newborn_workup(record, record.patient)
    assert wu["is_neonate"] is True
    assert wu["apgar_1min"] == 8
    assert wu["apgar_5min"] == 9
    assert wu["bilirubin_peak"] == 11.4
    assert wu["cchd_ru_spo2"] == 98
    assert wu["cchd_le_spo2"] == 97
    assert wu["has_aabr"] is True
    assert wu["has_metabolic"] is True
    assert wu["has_vitamin_k"] is True
    assert wu["has_ophthalmic"] is True


def test_build_newborn_workup_non_neonate_returns_empty() -> None:
    record = _neonate_record()
    record.patient = _adult_patient()
    assert _build_newborn_workup(record, record.patient) == {}


def test_build_newborn_workup_age_zero_infant_by_age_only() -> None:
    record = _neonate_record()
    record.patient = SimpleNamespace(
        patient_id="pt-baby-by-age",
        age=0,
        occupation="",  # missing occupation but age=0 gate hits
        chronic_conditions=[],
    )
    wu = _build_newborn_workup(record, record.patient)
    assert wu["is_neonate"] is True


def test_build_newborn_workup_missing_extensions_returns_defaults() -> None:
    record = SimpleNamespace(
        patient=_neonate_patient(),
        extensions=None,
        procedures=[],
        medication_administrations=[],
    )
    wu = _build_newborn_workup(record, record.patient)
    assert wu["is_neonate"] is True
    assert wu["apgar_1min"] is None
    assert wu["bilirubin_peak"] is None
    assert wu["has_aabr"] is False
    assert wu["has_vitamin_k"] is False


# ---------------------------------------------------------------------------
# _render_newborn_workup_summary
# ---------------------------------------------------------------------------


_FULL_WORKUP = {
    "is_neonate": True,
    "apgar_1min": 8,
    "apgar_5min": 9,
    "bilirubin_peak": 11.4,
    "cchd_ru_spo2": 98,
    "cchd_le_spo2": 97,
    "has_aabr": True,
    "has_metabolic": True,
    "has_vitamin_k": True,
    "has_ophthalmic": True,
}


def test_render_summary_en_full() -> None:
    out = _render_newborn_workup_summary(_FULL_WORKUP, lang="en")
    assert "Apgar 8(1 min) / 9(5 min)" in out
    assert "AABR hearing screen completed" in out
    assert "tandem-MS metabolic screen submitted" in out
    assert "peak total bilirubin 11.4 mg/dL" in out
    assert "CCHD SpO2 RU 98% / LE 97%" in out
    assert "Vitamin K administered" in out
    assert "ophthalmic prophylaxis administered" in out


def test_render_summary_ja_full() -> None:
    out = _render_newborn_workup_summary(_FULL_WORKUP, lang="ja")
    assert "Apgar 8(1分)/9(5分)" in out
    assert "AABR 聴覚スクリーン提出済" in out
    assert "タンデム MS 代謝異常症スクリーン提出済" in out
    assert "総ビリルビン最高値 11.4 mg/dL" in out
    assert "CCHD SpO2 右上肢 98% / 下肢 97%" in out
    assert "ビタミン K 投与済" in out
    assert "眼科的予防投与済" in out


def test_render_summary_empty_workup_returns_empty() -> None:
    assert _render_newborn_workup_summary({}, lang="en") == ""


def test_render_summary_partial_no_apgar_no_bili() -> None:
    partial = {
        "is_neonate": True,
        "apgar_1min": None,
        "apgar_5min": None,
        "bilirubin_peak": None,
        "cchd_ru_spo2": 99,
        "cchd_le_spo2": None,
        "has_aabr": False,
        "has_metabolic": False,
        "has_vitamin_k": True,
        "has_ophthalmic": False,
    }
    out = _render_newborn_workup_summary(partial, lang="en")
    assert "Apgar" not in out
    assert "AABR" not in out
    assert "CCHD SpO2 RU 99% / LE -" in out
    assert "Vitamin K administered" in out


# ---------------------------------------------------------------------------
# _build_extra_context integration — admission_hp only
# ---------------------------------------------------------------------------


class _Spec:
    def __init__(self, type_key: str) -> None:
        self.type_key = type_key


def _make_ctx_for_admission_hp(
    newborn_workup: dict,
    target_lang: str = "en",
) -> SimpleNamespace:
    encounter = SimpleNamespace(
        encounter_id="ENC-1",
        admission_datetime=datetime(2026, 7, 1, 10, 0),
        encounter_type=SimpleNamespace(value="inpatient"),
        primary_diagnosis="Z38.00",
    )
    return SimpleNamespace(
        patient=_neonate_patient(),
        encounter=encounter,
        encounter_type=encounter.encounter_type,
        disease_protocol=None,
        clinical_course_archetype="uncomplicated_improvement",
        severity="moderate",
        day_index=0,
        los_days=2,
        target_lang=target_lang,
        locale=target_lang,
        vitals=[],
        lab_results=[],
        medications=[],
        procedures=[],
        complications_occurred=[],
        working_diagnoses=[],
        discharge_medications=[],
        document_type=DocumentType.ADMISSION_HP,
        safety_skips=[],
        newborn_workup=newborn_workup,
    )


def test_extra_context_emits_newborn_workup_summary_on_admission_hp() -> None:
    ctx = _make_ctx_for_admission_hp(_FULL_WORKUP, target_lang="en")
    extra = _build_extra_context(ctx, _Spec("admission_hp"))
    assert "newborn_workup_summary" in extra
    assert "Apgar" in extra["newborn_workup_summary"]


def test_extra_context_skips_when_not_neonate() -> None:
    ctx = _make_ctx_for_admission_hp({}, target_lang="en")
    extra = _build_extra_context(ctx, _Spec("admission_hp"))
    assert "newborn_workup_summary" not in extra


def test_extra_context_skips_on_non_admission_hp_doc_type() -> None:
    ctx = _make_ctx_for_admission_hp(_FULL_WORKUP, target_lang="en")
    ctx.document_type = DocumentType.PROGRESS_NOTE
    extra = _build_extra_context(ctx, _Spec("progress_note"))
    assert "newborn_workup_summary" not in extra
