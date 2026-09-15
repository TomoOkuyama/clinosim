"""Regression guard: template body renders newborn workup in HPI (Issue #1432).

On the p=10000 s=359 verify, 851 US / 852 JP admission_hp Compositions
were emitted for neonatal encounters (Z38.0 admissions), but zero
``section.text.div`` contained an "Apgar" reference. The context wiring
for ``ctx.newborn_workup`` reaches the LLM prompt grounding (via
``replacement_strategy._build_extra_context``) but not the deterministic
template body — Apgar / bilirubin / CCHD / screening flags never made
it into the FHIR-emitted narrative text on the template pass.

Fix: when ``ctx.newborn_workup["is_neonate"]`` is true, append the
one-line workup summary rendered by
``replacement_strategy._render_newborn_workup_summary`` to the end of
the HPI section, terminated with the locale-appropriate sentence
punctuation. Non-neonate encounters must be untouched.
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from typing import Any

from clinosim.modules.document.narrative.template_generator import TemplateNarrativeGenerator
from clinosim.types.document import DocumentType, NarrativeContext
from clinosim.types.patient import PatientProfile


def _ctx(target_lang: str, newborn_workup: dict[str, Any]) -> NarrativeContext:
    patient = PatientProfile(patient_id="pt-baby-1432")
    patient.chronic_conditions = []
    patient.current_medications = []
    patient.allergies = []
    encounter = SimpleNamespace(
        encounter_id="enc-baby-1432",
        encounter_type=SimpleNamespace(value="inpatient"),
        admission_datetime=datetime(2026, 7, 1, 10, 0),
    )
    return NarrativeContext(
        patient=patient,
        encounter=encounter,
        encounter_type=encounter.encounter_type,
        disease_protocol=None,
        encounter_protocol=None,
        clinical_course_archetype="uncomplicated_improvement",
        severity="",
        day_index=0,
        los_days=2,
        vitals=[],
        lab_results=[],
        medications=[],
        diagnoses=[],
        procedures=[],
        allergies=[],
        document_type=DocumentType.ADMISSION_HP,
        target_lang=target_lang,
        locale="us" if target_lang == "en" else "jp",
        newborn_workup=newborn_workup,
    )


def _full_workup() -> dict[str, Any]:
    return {
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


def test_us_hpi_neonate_appends_apgar_and_workup_summary() -> None:
    """English HPI for a neonate must terminate with an Apgar-anchored
    workup line so the FHIR ``section.text.div`` no longer has zero
    "Apgar" hits on admission_hp for Z38.0 encounters."""
    gen = TemplateNarrativeGenerator()
    ctx = _ctx("en", newborn_workup=_full_workup())
    text, facts = gen._build_hpi(ctx)
    assert "Apgar 8(1 min) / 9(5 min)" in text
    assert "AABR hearing screen completed" in text
    assert "peak total bilirubin 11.4 mg/dL" in text
    assert "CCHD SpO2 RU 98% / LE 97%" in text
    assert "Vitamin K administered" in text
    assert "ophthalmic prophylaxis administered" in text
    # Fact trail must record the workup source.
    assert "ctx.newborn_workup" in facts


def test_jp_hpi_neonate_appends_apgar_and_workup_summary() -> None:
    """JA HPI must carry the same workup data with JA phrasing."""
    gen = TemplateNarrativeGenerator()
    ctx = _ctx("ja", newborn_workup=_full_workup())
    text, facts = gen._build_hpi(ctx)
    assert "Apgar 8(1分)/9(5分)" in text
    assert "AABR 聴覚スクリーン提出済" in text
    assert "総ビリルビン最高値 11.4 mg/dL" in text
    assert "CCHD SpO2 右上肢 98% / 下肢 97%" in text
    assert "ビタミン K 投与済" in text
    assert "眼科的予防投与済" in text
    assert "ctx.newborn_workup" in facts


def test_us_hpi_non_neonate_workup_omitted() -> None:
    """Non-neonate ctx (empty workup dict) must not add any workup text."""
    gen = TemplateNarrativeGenerator()
    ctx = _ctx("en", newborn_workup={})
    text, facts = gen._build_hpi(ctx)
    assert "Apgar" not in text
    assert "ctx.newborn_workup" not in facts


def test_us_hpi_neonate_with_empty_workup_omitted() -> None:
    """A neonate flag alone with no populated fields must not append an
    empty workup fragment or a bare sentence-terminator."""
    gen = TemplateNarrativeGenerator()
    ctx = _ctx("en", newborn_workup={"is_neonate": True})
    text, _facts = gen._build_hpi(ctx)
    assert "Apgar" not in text
    # No lone trailing sentinel like "" + "." remaining as a bare period
    # after a space.
    assert " ." not in text


def test_us_hpi_neonate_appends_after_existing_hpi_text() -> None:
    """The workup line is APPENDED, not replaced — the underlying
    empty-severity fallback stays intact so the doubled-space fingerprint
    #1266 guard remains in force."""
    gen = TemplateNarrativeGenerator()
    ctx = _ctx("en", newborn_workup=_full_workup())
    text, _facts = gen._build_hpi(ctx)
    assert text.startswith("Patient presented for evaluation.")
    assert "Apgar" in text  # appended after
