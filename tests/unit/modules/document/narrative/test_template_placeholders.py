"""β-JP-1 chain 1a T3 (spec §2c): encounter-template placeholder substitution.

The encounter YAML narrative templates (ed_note_template /
outpatient_soap_template) carry `{placeholder}` tokens (e.g. `{onset_days}`,
`{chief_complaint_en}`, `{lab_summary_ja}`). Until chain 1a these templates
never reached output (ctx.encounter_protocol was always None), so nothing
substituted them. Now that the protocol is wired, raw braces must not leak
into narrative text: known placeholders get real/default values.

adv-1 I-2: a template that still carries UNKNOWN placeholders falls back to
the whole-section generic phrase (pre-1a parity) — per-placeholder generic
substitution produced broken sentences ("BP No special findings/No special
findings mmHg").

β-JP-1 chain 1b T4: {sbp}/{dbp}/{hr}/{temp}/{spo2}/{rr} now resolve from
ctx.vitals (nearest non-null reading for the stub's day). No resolvable
reading → the I-2 whole-section fallback stays (pinned below with empty
vitals).
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


def test_ed_unknown_placeholder_falls_back_to_whole_section_generic():
    """adv-1 I-2: unknown placeholder → whole-section generic phrase.

    Per-placeholder substitution ("Labs obtained. No special findings.")
    produced broken sentences on numeric slots; the section falls back to the
    single coherent pre-1a generic phrase instead.
    """
    gen = TemplateNarrativeGenerator()
    out = gen.generate(_ctx(DocumentType.ED_NOTE, _ED_PROTOCOL), _spec("ed_note"))
    workup = out.sections["ed_workup"]
    assert workup == "No special findings"


def test_numeric_placeholders_fall_back_to_whole_section_generic_en():
    """adv-1 I-2 regression pin (chain 1b T4 refinement): EMPTY vitals →
    whole-section fallback stays — no 'BP No special findings/... mmHg'."""
    proto = {
        "condition_id": "chest_pain_noncardiac",
        "chief_complaint": {"en": "Chest pain", "ja": "胸痛"},
        "narrative": {
            "ed_note_template": {
                "ed_workup_summary_en": "BP {sbp}/{dbp} mmHg, HR {hr}/min.",
            },
        },
    }
    gen = TemplateNarrativeGenerator()
    out = gen.generate(_ctx(DocumentType.ED_NOTE, proto), _spec("ed_note"))
    workup = out.sections["ed_workup"]
    assert workup == "No special findings"
    assert "mmHg" not in workup


def test_numeric_placeholders_fall_back_to_whole_section_generic_ja():
    proto = {
        "condition_id": "prescription_renewal",
        "chief_complaint": {"en": "Prescription renewal", "ja": "処方継続"},
        "narrative": {
            "outpatient_soap_template": {
                "subjective_ja": "処方継続希望",
                "objective_ja": "バイタル安定（BP {sbp}/{dbp}、HR {hr}）。",
                "assessment_ja": "状態安定",
                "plan_ja": "処方継続",
            },
        },
    }
    ctx = _ctx(DocumentType.OUTPATIENT_SOAP, proto, lang="ja")
    ctx.encounter_type = "outpatient"
    gen = TemplateNarrativeGenerator()
    out = gen.generate(ctx, _spec("outpatient_soap", "jp"))
    obj = out.sections["objective"]
    assert obj == "特記事項なし"
    assert "mmHg" not in obj and "BP" not in obj


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
    # unknown placeholder-only section → whole-section generic phrase (I-2)
    assert out.sections["assessment"] == "特記事項なし"


def test_ed_physical_exam_mixed_parts_keeps_resolved_drops_unresolved():
    """adv-1 I-2: per-body-system parts with unknown placeholders are dropped.

    A part that falls back to the generic phrase carries no information and
    would repeat ("No special findings. No special findings.") — it is
    filtered; fully-resolvable parts are kept.
    """
    proto = {
        "condition_id": "abdominal_pain_nonspecific",
        "chief_complaint": {"en": "Abdominal pain", "ja": "腹痛"},
        "narrative": {
            "ed_note_template": {
                "physical_exam_en": {
                    "general": "Alert and oriented",
                    "cardiovascular": "BP {sbp}/{dbp} mmHg, HR {hr}/min",
                    "abdominal": "Tenderness: {pain_site_en}.",
                },
            },
        },
    }
    gen = TemplateNarrativeGenerator()
    out = gen.generate(_ctx(DocumentType.ED_NOTE, proto), _spec("ed_note"))
    pe = out.sections["physical_exam"]
    assert "{" not in pe and "}" not in pe
    assert pe == "Alert and oriented"


# --- β-JP-1 chain 1b T4: vitals placeholders from ctx.vitals ---


_VITALS_PROTOCOL = {
    "condition_id": "chest_pain_noncardiac",
    "chief_complaint": {"en": "Chest pain", "ja": "胸痛"},
    "narrative": {
        "ed_note_template": {
            "ed_workup_summary_en": (
                "BP {sbp}/{dbp} mmHg, HR {hr}/min, T {temp}C, SpO2 {spo2}%, RR {rr}/min."
            ),
        },
    },
}


def _vital(timestamp: str, **values):
    base = {
        "timestamp": timestamp,
        "temperature_celsius": None,
        "heart_rate": None,
        "systolic_bp": None,
        "diastolic_bp": None,
        "respiratory_rate": None,
        "spo2": None,
    }
    base.update(values)
    return base


def test_vitals_placeholders_resolve_from_ctx_vitals():
    ctx = _ctx(DocumentType.ED_NOTE, _VITALS_PROTOCOL)
    ctx.encounter = {"encounter_id": "ENC-1", "admission_datetime": "2025-01-10T09:00:00"}
    ctx.vitals = [_vital(
        "2025-01-10T10:00:00",
        systolic_bp=132, diastolic_bp=84, heart_rate=88,
        temperature_celsius=37.25, spo2=97.0, respiratory_rate=18,
    )]
    gen = TemplateNarrativeGenerator()
    out = gen.generate(ctx, _spec("ed_note"))
    workup = out.sections["ed_workup"]
    assert workup == "BP 132/84 mmHg, HR 88/min, T 37.2C, SpO2 97%, RR 18/min."


def test_vitals_placeholders_pick_nearest_day_reading():
    """day_index selects the reading closest to admission + N days."""
    proto = {
        "condition_id": "chest_pain_noncardiac",
        "chief_complaint": {"en": "Chest pain", "ja": "胸痛"},
        "narrative": {
            "ed_note_template": {"ed_workup_summary_en": "HR {hr}/min."},
        },
    }
    ctx = _ctx(DocumentType.ED_NOTE, proto)
    ctx.encounter = {"encounter_id": "ENC-1", "admission_datetime": "2025-01-10T09:00:00"}
    ctx.day_index = 1
    ctx.vitals = [
        _vital("2025-01-10T10:00:00", heart_rate=110),  # day 0
        _vital("2025-01-11T10:00:00", heart_rate=92),   # day 1 ← nearest
        _vital("2025-01-12T10:00:00", heart_rate=78),   # day 2
    ]
    gen = TemplateNarrativeGenerator()
    out = gen.generate(ctx, _spec("ed_note"))
    assert out.sections["ed_workup"] == "HR 92/min."


def test_vitals_placeholder_skips_null_reading_to_next_nearest():
    """A null field on the nearest reading falls through to the next one."""
    proto = {
        "condition_id": "viral_uri",
        "chief_complaint": {"en": "Sore throat", "ja": "咽頭痛"},
        "narrative": {
            "ed_note_template": {"ed_workup_summary_en": "T {temp}C, HR {hr}/min."},
        },
    }
    ctx = _ctx(DocumentType.ED_NOTE, proto)
    ctx.encounter = {"encounter_id": "ENC-1", "admission_datetime": "2025-01-10T09:00:00"}
    ctx.vitals = [
        _vital("2025-01-10T10:00:00", heart_rate=104),                 # temp null here
        _vital("2025-01-10T16:00:00", temperature_celsius=38.6),      # temp from here
    ]
    gen = TemplateNarrativeGenerator()
    out = gen.generate(ctx, _spec("ed_note"))
    assert out.sections["ed_workup"] == "T 38.6C, HR 104/min."


def test_vitals_placeholder_unresolvable_keeps_section_fallback():
    """All readings null for a needed field → I-2 whole-section fallback stays."""
    proto = {
        "condition_id": "chest_pain_noncardiac",
        "chief_complaint": {"en": "Chest pain", "ja": "胸痛"},
        "narrative": {
            "ed_note_template": {"ed_workup_summary_en": "BP {sbp}/{dbp} mmHg."},
        },
    }
    ctx = _ctx(DocumentType.ED_NOTE, proto)
    ctx.encounter = {"encounter_id": "ENC-1", "admission_datetime": "2025-01-10T09:00:00"}
    ctx.vitals = [_vital("2025-01-10T10:00:00", heart_rate=88)]  # no BP anywhere
    gen = TemplateNarrativeGenerator()
    out = gen.generate(ctx, _spec("ed_note"))
    assert out.sections["ed_workup"] == "No special findings"


def test_vitals_mixed_with_unknown_placeholder_still_falls_back():
    """Resolvable vitals + one unknown placeholder → whole-section fallback (I-2)."""
    proto = {
        "condition_id": "prescription_renewal",
        "chief_complaint": {"en": "Prescription renewal", "ja": "処方継続"},
        "narrative": {
            "ed_note_template": {
                "ed_workup_summary_en": "BP {sbp}/{dbp}, BW {weight}kg.",
            },
        },
    }
    ctx = _ctx(DocumentType.ED_NOTE, proto)
    ctx.encounter = {"encounter_id": "ENC-1", "admission_datetime": "2025-01-10T09:00:00"}
    ctx.vitals = [_vital("2025-01-10T10:00:00", systolic_bp=120, diastolic_bp=70)]
    gen = TemplateNarrativeGenerator()
    out = gen.generate(ctx, _spec("ed_note"))
    assert out.sections["ed_workup"] == "No special findings"


def test_vitals_placeholders_deterministic():
    """Same ctx twice → identical output (no RNG in the resolution path)."""
    def _build():
        ctx = _ctx(DocumentType.ED_NOTE, _VITALS_PROTOCOL)
        ctx.encounter = {
            "encounter_id": "ENC-1", "admission_datetime": "2025-01-10T09:00:00",
        }
        ctx.vitals = [
            _vital("2025-01-10T10:00:00", systolic_bp=132, diastolic_bp=84,
                   heart_rate=88, temperature_celsius=37.25, spo2=97.0,
                   respiratory_rate=18),
            _vital("2025-01-10T18:00:00", systolic_bp=128, diastolic_bp=80,
                   heart_rate=84, temperature_celsius=37.0, spo2=98.0,
                   respiratory_rate=16),
        ]
        return TemplateNarrativeGenerator().generate(ctx, _spec("ed_note"))

    assert _build().sections["ed_workup"] == _build().sections["ed_workup"]


def test_ed_physical_exam_all_parts_unresolved_falls_back_once():
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
    # single whole-section generic phrase, not one per body system
    assert out.sections["physical_exam"] == "No special findings"
