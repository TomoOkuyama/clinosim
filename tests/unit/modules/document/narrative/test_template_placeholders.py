"""β-JP-1 chain 1a T3 (spec §2c): encounter-template placeholder substitution.

The encounter YAML narrative templates (ed_note_template /
outpatient_soap_template) carry `{placeholder}` tokens (e.g. `{onset_days}`,
`{chief_complaint_en}`, `{lab_summary_ja}`). Until chain 1a these templates
never reached output (ctx.encounter_protocol was always None), so nothing
substituted them. Now that the protocol is wired, raw braces must not leak
into narrative text: known placeholders get real/default values, unknown
ones fall back to the locale generic phrase.
"""

from __future__ import annotations

import pytest

from clinosim.modules.document import specs_for_country
from clinosim.modules.document.narrative.template_generator import (
    TemplateNarrativeGenerator,
)
from clinosim.types.document import DocumentType, NarrativeContext

pytestmark = pytest.mark.unit


def _spec(type_key: str, country: str = "us"):
    for s in specs_for_country(country):
        if s.type_key == type_key:
            return s
    raise AssertionError(f"spec {type_key} not found")


def _ctx(document_type: DocumentType, encounter_protocol: dict, lang: str = "en"):
    return NarrativeContext(
        patient={"patient_id": "P1"},
        encounter={"encounter_id": "ENC-1"},
        encounter_type="emergency",
        disease_protocol=None,
        encounter_protocol=encounter_protocol,
        clinical_course_archetype="",
        severity="moderate",
        day_index=0,
        los_days=1,
        vitals=[],
        lab_results=[],
        medications=[],
        diagnoses=[],
        procedures=[],
        allergies=[],
        document_type=document_type,
        target_lang=lang,
        locale="us" if lang == "en" else "jp",
    )


_ED_PROTOCOL = {
    "condition_id": "abdominal_pain_nonspecific",
    "chief_complaint": {"en": "Abdominal pain, nausea", "ja": "腹痛・嘔気"},
    "narrative": {
        "ed_note_template": {
            "chief_complaint_en": "{chief_complaint_en}",
            "hpi_en": "Onset {onset_days} day(s) ago: {chief_complaint_en}.",
            "ed_workup_summary_en": "Labs obtained. {imaging_summary_en}.",
            "disposition_en": "Discharged home.",
        },
    },
}


def test_ed_hpi_substitutes_onset_days_and_chief_complaint():
    gen = TemplateNarrativeGenerator()
    out = gen.generate(_ctx(DocumentType.ED_NOTE, _ED_PROTOCOL), _spec("ed_note"))
    hpi = out.sections["hpi"]
    assert "{" not in hpi and "}" not in hpi
    assert "Abdominal pain, nausea" in hpi
    assert "3 day(s) ago" in hpi  # documented fixed default (module docstring)


def test_ed_unknown_placeholder_falls_back_to_generic_phrase():
    gen = TemplateNarrativeGenerator()
    out = gen.generate(_ctx(DocumentType.ED_NOTE, _ED_PROTOCOL), _spec("ed_note"))
    workup = out.sections["ed_workup"]
    assert "{" not in workup and "}" not in workup
    assert "no significant findings" in workup.lower() or "Labs obtained" in workup


def test_ed_text_without_placeholders_unchanged():
    gen = TemplateNarrativeGenerator()
    out = gen.generate(_ctx(DocumentType.ED_NOTE, _ED_PROTOCOL), _spec("ed_note"))
    assert out.sections["disposition"] == "Discharged home."


def test_soap_subjective_substitutes_placeholders_ja():
    proto = {
        "condition_id": "annual_health_screening",
        "chief_complaint": {"en": "Health checkup", "ja": "健康診断"},
        "narrative": {
            "outpatient_soap_template": {
                "subjective_ja": "{chief_complaint_ja}の訴え、{onset_days}日前より",
                "objective_ja": "バイタル安定",
                "assessment_ja": "{primary_dx_display_ja}",
                "plan_ja": "経過観察",
            },
        },
    }
    ctx = _ctx(DocumentType.OUTPATIENT_SOAP, proto, lang="ja")
    ctx.encounter_type = "outpatient"
    gen = TemplateNarrativeGenerator()
    out = gen.generate(ctx, _spec("outpatient_soap", "jp"))
    subj = out.sections["subjective"]
    assert "{" not in subj
    assert "健康診断" in subj
    assert "3日前より" in subj
    # unknown placeholder-only section → generic phrase, no braces
    assert "{" not in out.sections["assessment"]


def test_ed_physical_exam_substitutes_placeholders():
    proto = {
        "condition_id": "abdominal_pain_nonspecific",
        "chief_complaint": {"en": "Abdominal pain", "ja": "腹痛"},
        "narrative": {
            "ed_note_template": {
                "physical_exam_en": {
                    "general": "Alert and oriented, {severity_desc_en}",
                    "abdominal": "Tenderness: {pain_site_en}.",
                },
            },
        },
    }
    gen = TemplateNarrativeGenerator()
    out = gen.generate(_ctx(DocumentType.ED_NOTE, proto), _spec("ed_note"))
    pe = out.sections["physical_exam"]
    assert "{" not in pe and "}" not in pe
    assert "Alert and oriented" in pe
