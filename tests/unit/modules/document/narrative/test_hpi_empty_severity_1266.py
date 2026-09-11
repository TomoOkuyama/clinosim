"""Regression guard for the empty-`severity` HPI fallback (#1266).

Newborn Z38.0 US admissions have no disease-graded severity (Z38.0 is
not a graded illness), so the `_build_hpi` / `_build_present_illness`
/ `_build_present_illness_ref` fallback interpolated an empty string
into the sentence:

    fallback = f"Patient presented with {ctx.severity} symptoms."
    → "Patient presented with  symptoms."   (doubled space)

At s=351 p=10 000: **256/897 (28.5 %)** US admission_hp Compositions
carried this fingerprint. Fix: guard the sentence — when severity is
empty use the natural chief-complaint-less form ("Patient presented
for evaluation.") without a doubled-space blank.

JP path was cosmetically weaker too (`"の症状で受診。"` starting with
の), so the guard is applied symmetrically.
"""

from __future__ import annotations

import re
from datetime import datetime
from types import SimpleNamespace

from clinosim.modules.document.narrative.template_generator import TemplateNarrativeGenerator
from clinosim.types.document import DocumentType, NarrativeContext
from clinosim.types.patient import PatientProfile

_DOUBLE_SPACE_FINGERPRINT = re.compile(r"presented with\s{2,}symptoms")


def _ctx(target_lang: str, severity: str) -> NarrativeContext:
    patient = PatientProfile(patient_id="pt-baby")
    patient.chronic_conditions = []
    patient.current_medications = []
    patient.allergies = []
    encounter = SimpleNamespace(
        encounter_id="enc-baby",
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
        severity=severity,
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
    )


def test_us_hpi_empty_severity_no_double_space() -> None:
    """The doubled-space fingerprint that #1266 was filed on must be
    absent from every HPI-producing builder even when severity is empty.
    """
    gen = TemplateNarrativeGenerator()
    ctx = _ctx("en", severity="")
    hpi_text, _ = gen._build_hpi(ctx)
    pi_text, _ = gen._build_present_illness(ctx)
    pi_ref_text, _ = gen._build_present_illness_ref(ctx)
    for label, text in (
        ("_build_hpi", hpi_text),
        ("_build_present_illness", pi_text),
        ("_build_present_illness_ref", pi_ref_text),
    ):
        assert not _DOUBLE_SPACE_FINGERPRINT.search(text), (
            f"{label} still ships the doubled-space fingerprint: {text!r}"
        )


def test_us_hpi_empty_severity_uses_evaluation_fallback() -> None:
    """The empty-severity US fallback must land on the natural
    chief-complaint-less form. `_build_present_illness` and
    `_build_present_illness_ref` both delegate to `_build_hpi` on the
    no-disease-protocol path, so all three ship the same sentence.
    """
    gen = TemplateNarrativeGenerator()
    ctx = _ctx("en", severity="")
    hpi_text, _ = gen._build_hpi(ctx)
    assert hpi_text == "Patient presented for evaluation."
    pi_text, _ = gen._build_present_illness(ctx)
    assert pi_text == "Patient presented for evaluation."
    pi_ref_text, _ = gen._build_present_illness_ref(ctx)
    assert pi_ref_text == "Patient presented for evaluation."


def test_us_hpi_nonempty_severity_still_interpolates() -> None:
    """Severity present → keep the original graded-severity sentence."""
    gen = TemplateNarrativeGenerator()
    ctx = _ctx("en", severity="moderate")
    hpi_text, _ = gen._build_hpi(ctx)
    assert hpi_text == "Patient presented with moderate symptoms."


def test_jp_hpi_empty_severity_uses_evaluation_fallback() -> None:
    """JP path guarded symmetrically — no leading-の grammar oddity."""
    gen = TemplateNarrativeGenerator()
    ctx = _ctx("ja", severity="")
    hpi_text, _ = gen._build_hpi(ctx)
    assert hpi_text == "受診となった。"


def test_jp_hpi_nonempty_severity_still_interpolates() -> None:
    """JP-side non-empty severity: keep the original 症状で受診 sentence."""
    gen = TemplateNarrativeGenerator()
    ctx = _ctx("ja", severity="moderate")
    hpi_text, _ = gen._build_hpi(ctx)
    assert hpi_text == "中等度の症状で受診。"
