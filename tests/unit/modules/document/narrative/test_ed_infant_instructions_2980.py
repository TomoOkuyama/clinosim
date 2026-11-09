"""Infants are not advised honey for cough (Issue #2980).

Honey must not be given under 12 months (infant botulism; AAP, CDC). An ED
discharge instruction may carry ``min_age_months`` with a ``younger``
variant, which a patient below that age gets instead.
"""

from __future__ import annotations

import pytest

from clinosim.modules.document.narrative.renderers.section_builders.ed_note import build_ed_disposition
from clinosim.modules.document.narrative.template_generator import TemplateNarrativeGenerator
from clinosim.modules.encounter.protocol import (
    EncounterConditionProtocol,
    discharge_instructions_for_age,
    load_all_encounter_conditions,
    load_encounter_condition,
)
from clinosim.types.document import DocumentType, NarrativeContext

pytestmark = pytest.mark.unit

_GEN = TemplateNarrativeGenerator()
_HONEY = {"en": "honey", "ja": "蜂蜜"}


def _ctx(dob: str, lang: str) -> NarrativeContext:
    return NarrativeContext(
        patient={"patient_id": "P2980", "date_of_birth": dob, "age": 0},
        encounter={
            "encounter_id": "ENC-2980",
            "encounter_type": "emergency",
            "chief_complaint": "Fever, cough",
            "severity": "mild",
            "discharge_disposition": "home",
            "admission_datetime": "2026-03-01T10:00:00",
            "triage_data": {"level": "4", "level_system": "ESI"},
        },
        encounter_type="emergency",
        disease_protocol=None,
        encounter_protocol=load_encounter_condition("viral_uri"),
        clinical_course_archetype="",
        severity="mild",
        day_index=0,
        los_days=1,
        vitals=[],
        lab_results=[],
        medications=[],
        diagnoses=[],
        procedures=[],
        allergies=[],
        document_type=DocumentType.ED_NOTE,
        target_lang=lang,
        locale="us" if lang == "en" else "jp",
    )


@pytest.mark.parametrize("lang", ["en", "ja"])
def test_uri_instructions_for_a_6_month_old_do_not_mention_honey(lang: str) -> None:
    text, _ = build_ed_disposition(_GEN, _ctx("2025-09-01", lang))
    assert _HONEY[lang] not in text, text
    assert ("saline" if lang == "en" else "生理食塩水") in text
    assert ("suction" if lang == "en" else "吸引") in text


@pytest.mark.parametrize("lang", ["en", "ja"])
def test_uri_instructions_for_a_child_over_12_months_keep_honey(lang: str) -> None:
    text, _ = build_ed_disposition(_GEN, _ctx("2024-09-01", lang))
    assert _HONEY[lang] in text, text


def test_age_gate_boundary_is_12_months() -> None:
    proto = load_encounter_condition("viral_uri")
    at_11 = " ".join(i["en"] for i in discharge_instructions_for_age(proto, 11))
    at_12 = " ".join(i["en"] for i in discharge_instructions_for_age(proto, 12))
    assert "honey" not in at_11 and "honey" in at_12


def test_no_younger_variant_of_any_emergency_protocol_mentions_honey() -> None:
    for cid, proto in load_all_encounter_conditions().items():
        for item in discharge_instructions_for_age(proto, 0):
            text = item if isinstance(item, str) else " ".join(item.values())
            assert "honey" not in text.lower() and "蜂蜜" not in text, cid


def test_a_gated_instruction_needs_a_bilingual_younger_variant() -> None:
    raw = dict(load_encounter_condition("viral_uri"))
    raw["discharge_instructions"] = [{"en": "Honey for cough", "ja": "咳に蜂蜜", "min_age_months": 12}]
    with pytest.raises(ValueError, match="younger"):
        EncounterConditionProtocol.model_validate(raw)
