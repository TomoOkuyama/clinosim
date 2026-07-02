"""β-JP-1 chain 1a T3 (spec §2c): discharge_diagnoses display resolution (AD-30).

ctx.diagnoses is newly wired (clinical_diagnosis dict), so the
discharge_diagnoses section would emit bare ICD codes ("I63.9") — flagged by
the JP language integration gate (non-JP text in JP-capable section). AD-30:
CIF stores codes; display text resolves at output time via clinosim.codes.
"""

from __future__ import annotations

import pytest

from clinosim.modules.document import specs_for_country
from clinosim.modules.document.narrative.template_generator import (
    TemplateNarrativeGenerator,
)
from clinosim.types.document import DocumentType, NarrativeContext

pytestmark = pytest.mark.unit


def _spec(country: str):
    for s in specs_for_country(country):
        if s.type_key == "discharge_summary":
            return s
    raise AssertionError("discharge_summary spec not found")


def _ctx(lang: str, system: str, code: str):
    return NarrativeContext(
        patient={"patient_id": "P1"},
        encounter={"encounter_id": "ENC-1"},
        encounter_type="inpatient",
        disease_protocol=None,
        encounter_protocol=None,
        clinical_course_archetype="",
        severity="moderate",
        day_index=4,
        los_days=5,
        vitals=[],
        lab_results=[],
        medications=[],
        diagnoses=[{
            "admission_diagnosis_code": code,
            "admission_diagnosis_system": system,
            "discharge_diagnosis_code": code,
            "discharge_diagnosis_system": system,
        }],
        procedures=[],
        allergies=[],
        document_type=DocumentType.DISCHARGE_SUMMARY,
        target_lang=lang,
        locale="jp" if lang == "ja" else "us",
    )


def test_jp_discharge_diagnoses_resolves_japanese_display():
    gen = TemplateNarrativeGenerator()
    out = gen.generate(_ctx("ja", "icd-10", "I63.9"), _spec("jp"))
    text = out.sections["discharge_diagnoses"]
    assert "脳梗塞" in text  # authoritative ja display from codes/data/icd-10.yaml
    assert "I63.9" in text  # code retained for unambiguity


def test_us_discharge_diagnoses_resolves_english_display():
    gen = TemplateNarrativeGenerator()
    out = gen.generate(_ctx("en", "icd-10-cm", "I21.9"), _spec("us"))
    text = out.sections["discharge_diagnoses"]
    assert "myocardial infarction" in text.lower()
    assert "I21.9" in text


def test_unresolvable_code_falls_back_to_code_only():
    gen = TemplateNarrativeGenerator()
    out = gen.generate(_ctx("en", "icd-10-cm", "ZZZ99.99"), _spec("us"))
    assert out.sections["discharge_diagnoses"] == "ZZZ99.99"
