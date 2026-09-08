"""DM Assessment Nathan-formula consistency — Issue #1188 F4.

Before the fix, the DM (E10/E11) Assessment builder unconditionally
cited both HbA1c and glucose from independent CIF observations.
When HbA1c was elevated (poor long-term control) but glucose was
sampled from a normoglycemic distribution, the line read
`HbA1c 9.0% コントロール不十分, 血糖 128 mg/dL` — clinically
implausible per Nathan (`eAG ≈ 28.7 × HbA1c − 46.7 = 212 mg/dL for
HbA1c 9.0`).

The fix skips the glucose citation when the reported glucose is
>60 mg/dL below the Nathan-expected eAG and HbA1c ≥ 8.0. HbA1c
alone remains the more meaningful long-term marker.
"""

from __future__ import annotations

from datetime import date, datetime
from types import SimpleNamespace

from clinosim.modules.document.narrative.template_generator import (
    TemplateNarrativeGenerator,
)
from clinosim.types.document import DocumentType, NarrativeContext
from clinosim.types.patient import PatientProfile


def _mk_ctx(labs: list, lang: str = "ja") -> NarrativeContext:
    p = PatientProfile(patient_id="pt-1188")
    p.chronic_conditions = [SimpleNamespace(code="E11.9")]
    p.current_medications = []
    p.age = 65
    p.sex = "M"
    p.date_of_birth = date(1960, 1, 1)
    enc = SimpleNamespace(encounter_id="enc-1188", admission_datetime=datetime(2026, 5, 1, 10, 0))
    return NarrativeContext(
        patient=p,
        encounter=enc,
        encounter_type=None,
        disease_protocol=None,
        encounter_protocol=None,
        clinical_course_archetype="uncomplicated_improvement",
        severity="moderate",
        day_index=0,
        los_days=1,
        vitals=[],
        lab_results=labs,
        medications=[],
        diagnoses=[],
        procedures=[],
        allergies=[],
        document_type=DocumentType.OUTPATIENT_SOAP,
        target_lang=lang,
        locale="jp" if lang == "ja" else "us",
    )


def _lab(name: str, value: float, unit: str = ""):
    return SimpleNamespace(lab_name=name, value=value, unit=unit)


def _run(ctx: NarrativeContext) -> str:
    return TemplateNarrativeGenerator()._compose_chronic_assessment_integrated(ctx)


def test_low_glucose_high_hba1c_skips_glucose() -> None:
    # HbA1c 9.0 → eAG ≈ 212. glucose 128 mg/dL is 84 below eAG → skip.
    ctx = _mk_ctx([_lab("HbA1c", 9.0, "%"), _lab("Glucose", 128, "mg/dL")])
    text = _run(ctx)
    assert "HbA1c 9.0" in text
    assert "血糖 128" not in text


def test_matching_glucose_and_hba1c_both_cited() -> None:
    # HbA1c 6.0 → eAG ≈ 125. glucose 124 mg/dL is within tolerance → cite both.
    ctx = _mk_ctx([_lab("HbA1c", 6.0, "%"), _lab("Glucose", 124, "mg/dL")])
    text = _run(ctx)
    assert "HbA1c 6.0" in text
    assert "血糖 124" in text


def test_glucose_only_no_hba1c_cited() -> None:
    # No HbA1c present → the Nathan gate is skipped; glucose emitted as-is.
    ctx = _mk_ctx([_lab("Glucose", 128, "mg/dL")])
    text = _run(ctx)
    assert "血糖 128" in text


def test_hba1c_borderline_low_skips_glucose_when_still_inconsistent() -> None:
    # HbA1c 8.0 → eAG ≈ 183. glucose 100 mg/dL is 83 below → skip.
    ctx = _mk_ctx([_lab("HbA1c", 8.0, "%"), _lab("Glucose", 100, "mg/dL")])
    text = _run(ctx)
    assert "血糖 100" not in text


def test_hba1c_below_8_glucose_kept_even_if_inconsistent() -> None:
    # HbA1c 7.5 → eAG ≈ 168. glucose 90 mg/dL is 78 below eAG,
    # but the gate only fires at HbA1c >= 8.0, so glucose is cited.
    ctx = _mk_ctx([_lab("HbA1c", 7.5, "%"), _lab("Glucose", 90, "mg/dL")])
    text = _run(ctx)
    assert "血糖 90" in text


def test_hba1c_high_glucose_matching_kept() -> None:
    # HbA1c 9.0 → eAG ≈ 212. glucose 200 mg/dL is only 12 below → cite both.
    ctx = _mk_ctx([_lab("HbA1c", 9.0, "%"), _lab("Glucose", 200, "mg/dL")])
    text = _run(ctx)
    assert "HbA1c 9.0" in text
    assert "血糖 200" in text
