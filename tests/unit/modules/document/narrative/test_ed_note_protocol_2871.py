"""The ED note follows its encounter protocol (Issue #2871).

HPI: the protocol's own template, with an onset of hours before arrival for
an injury and of days for an illness (drawn per encounter within the
protocol's ``narrative.onset`` range). Physical exam: the general appearance
follows the triage level. Assessment: the encounter's diagnosis. Disposition:
the protocol's discharge instructions and follow-up for a patient sent home.
"""

from __future__ import annotations

import re
import string
from typing import Any

import pytest

from clinosim.modules.document import specs_for_country
from clinosim.modules.document.narrative.registry import load_document_type_specs
from clinosim.modules.document.narrative.renderers.section_builders._registry import (
    document_section_builders,
)
from clinosim.modules.document.narrative.renderers.section_builders.ed_note import (
    build_ed_assessment,
    build_ed_disposition,
    build_ed_physical_exam,
)
from clinosim.modules.document.narrative.renderers.section_builders.hpi import build_hpi
from clinosim.modules.document.narrative.template_generator import TemplateNarrativeGenerator
from clinosim.modules.encounter.protocol import (
    EncounterConditionProtocol,
    load_all_encounter_conditions,
    load_encounter_condition,
)
from clinosim.types.document import DocumentType, NarrativeContext

pytestmark = pytest.mark.unit

_GEN = TemplateNarrativeGenerator()
_DX_SYSTEM = {"en": "icd-10-cm", "ja": "icd-10-mhlw"}


def _encounter(enc_id: str = "ENC-ED-1", *, level: str = "3", disposition: str = "home", **extra: Any) -> dict:
    return {
        "encounter_id": enc_id,
        "encounter_type": "emergency",
        "chief_complaint": extra.pop("chief_complaint", "Laceration requiring sutures"),
        "severity": "moderate",
        "discharge_disposition": disposition,
        "triage_data": {"level": level, "level_system": "ESI"},
        **extra,
    }


def _ctx(
    condition_id: str | None,
    lang: str = "en",
    *,
    encounter: dict | None = None,
    dx_code: str = "",
) -> NarrativeContext:
    encounter = encounter or _encounter()
    diagnoses = (
        [{"admission_diagnosis_code": dx_code, "admission_diagnosis_system": _DX_SYSTEM[lang]}] if dx_code else []
    )
    return NarrativeContext(
        patient={"patient_id": "P1"},
        encounter=encounter,
        encounter_type=encounter["encounter_type"],
        disease_protocol=None,
        encounter_protocol=load_encounter_condition(condition_id) if condition_id else None,
        clinical_course_archetype="",
        severity="moderate",
        day_index=0,
        los_days=1,
        vitals=[],
        lab_results=[],
        medications=[],
        diagnoses=diagnoses,
        procedures=[],
        allergies=[],
        document_type=DocumentType.ED_NOTE,
        target_lang=lang,
        locale="us" if lang == "en" else "jp",
    )


def _emergency_protocols() -> dict[str, dict]:
    return {cid: p for cid, p in load_all_encounter_conditions().items() if p.get("encounter_type") == "emergency"}


# ── HPI ──────────────────────────────────────────────────────────────────


def test_injury_hpi_states_hours_before_arrival_en() -> None:
    hpi, _ = build_hpi(_GEN, _ctx("minor_laceration"))
    assert re.search(r"Sustained a laceration about \d+ hours? before arrival", hpi), hpi
    assert "day" not in hpi and "progressively worsening" not in hpi


def test_injury_hpi_states_hours_before_arrival_ja() -> None:
    hpi, _ = build_hpi(_GEN, _ctx("minor_laceration", "ja"))
    assert re.match(r"来院約\d+時間前に裂傷を受傷", hpi), hpi
    assert "日前" not in hpi


def test_illness_hpi_states_days_within_the_protocol_range() -> None:
    low, high = load_encounter_condition("viral_uri")["narrative"]["onset"]["range"]
    seen = set()
    for i in range(30):
        ctx = _ctx("viral_uri", encounter=_encounter(f"ENC-{i}"))
        hpi, _ = build_hpi(_GEN, ctx)
        m = re.search(r"began (\d+) days? ago", hpi)
        assert m, hpi
        seen.add(int(m.group(1)))
    assert seen <= set(range(low, high + 1))
    assert len(seen) > 1  # drawn per encounter, not one fixed number


def test_illness_hpi_ja_uses_days() -> None:
    hpi, _ = build_hpi(_GEN, _ctx("viral_uri", "ja"))
    assert re.match(r"\d+日前より発熱・咽頭痛・咳嗽・鼻汁が出現", hpi), hpi


def test_onset_is_stable_for_one_encounter() -> None:
    first, _ = build_hpi(_GEN, _ctx("food_poisoning", encounter=_encounter("ENC-X")))
    again, _ = build_hpi(_GEN, _ctx("food_poisoning", encounter=_encounter("ENC-X")))
    assert first == again


@pytest.mark.parametrize("cid", ["chest_pain_noncardiac", "ankle_sprain"])
@pytest.mark.parametrize("lang", ["en", "ja"])
def test_protocol_specific_hpi_is_rendered(cid: str, lang: str) -> None:
    hpi, facts = build_hpi(_GEN, _ctx(cid, lang))
    assert f"encounter_protocol.narrative.ed_note_template.hpi_{lang}" in facts
    assert "No special findings" not in hpi and "特記事項なし" not in hpi


@pytest.mark.parametrize("lang", ["en", "ja"])
def test_every_emergency_protocol_hpi_resolves(lang: str) -> None:
    for cid in _emergency_protocols():
        hpi, facts = build_hpi(_GEN, _ctx(cid, lang))
        assert f"encounter_protocol.narrative.ed_note_template.hpi_{lang}" in facts, (cid, hpi)
        assert "{" not in hpi and "progressively worsening" not in hpi, (cid, hpi)


def test_hours_onset_protocols_do_not_use_a_day_count() -> None:
    """``{onset_days}`` has no value for an hours onset; such a template would
    collapse to the generic phrase."""
    for cid, proto in _emergency_protocols().items():
        onset = (proto.get("narrative") or {}).get("onset") or {}
        if onset.get("unit") != "hours":
            continue
        for text in (proto["narrative"]["ed_note_template"].get("hpi") or {}).values():
            names = {f for _, f, _, _ in string.Formatter().parse(text) if f}
            assert "onset_days" not in names, cid


# ── Physical exam: general appearance ───────────────────────────────────


@pytest.mark.parametrize(
    ("level", "en", "ja"),
    [
        ("1", "in acute distress", "苦悶様"),
        ("2", "in acute distress", "苦悶様"),
        ("3", "appears uncomfortable", "やや苦痛様"),
        ("4", "in no acute distress", "苦痛様顔貌なし"),
        ("5", "in no acute distress", "苦痛様顔貌なし"),
    ],
)
def test_general_appearance_follows_triage_level(level: str, en: str, ja: str) -> None:
    text_en, _ = build_ed_physical_exam(_GEN, _ctx("minor_laceration", encounter=_encounter(level=level)))
    assert text_en == f"Alert and oriented, {en}"
    text_ja, _ = build_ed_physical_exam(_GEN, _ctx("minor_laceration", "ja", encounter=_encounter(level=level)))
    assert f"意識清明、{ja}" in text_ja


def test_low_acuity_note_never_says_visible_distress() -> None:
    for cid in _emergency_protocols():
        text, _ = build_ed_physical_exam(_GEN, _ctx(cid, encounter=_encounter(level="5")))
        assert "visible distress" not in text and "in acute distress" not in text, (cid, text)


# ── Assessment ──────────────────────────────────────────────────────────


def test_assessment_states_the_ed_diagnosis_en() -> None:
    text, facts = build_ed_assessment(_GEN, _ctx("minor_laceration", dx_code="T14.90"))
    assert text == "ED diagnosis: Injury, unspecified. Chief complaint: Laceration requiring sutures."
    assert "ctx.diagnoses.admission_diagnosis_code" in facts


def test_assessment_states_the_ed_diagnosis_ja() -> None:
    enc = _encounter(chief_complaint="裂傷（縫合が必要）")
    text, _ = build_ed_assessment(_GEN, _ctx("minor_laceration", "ja", encounter=enc, dx_code="T14.90"))
    assert text == "救急外来診断: 部位不明の損傷。主訴: 裂傷（縫合が必要）。"


def test_assessment_without_a_diagnosis_uses_the_shared_builder() -> None:
    text, _ = build_ed_assessment(_GEN, _ctx("minor_laceration"))
    assert text == "Encounter reason: Laceration requiring sutures"


def test_ed_note_renders_its_own_assessment_builder() -> None:
    spec = next(s for s in specs_for_country("us") if s.type_key == "ed_note")
    out = _GEN.generate(_ctx("minor_laceration", dx_code="T14.90"), spec)
    assert out.sections["assessment"].startswith("ED diagnosis: Injury, unspecified.")


def test_document_type_builders_name_a_section_of_that_document() -> None:
    specs = load_document_type_specs()
    for doc_type, name in document_section_builders():
        sections = {s for country in ("US", "JP") for s in specs[doc_type].composition_sections_for(country)}
        assert name in sections, (doc_type, name)


# ── Disposition ─────────────────────────────────────────────────────────


def test_discharged_patient_gets_instructions_and_follow_up_en() -> None:
    text, facts = build_ed_disposition(_GEN, _ctx("minor_laceration", encounter=_encounter(level="4")))
    assert text.startswith("Discharged home (ESI level 4, Laceration requiring sutures). Discharge instructions: ")
    assert "Keep wound clean and dry for 24 hours; " in text
    assert text.endswith("Follow-up: suture removal in 7-10 days (face 5 days).")
    assert {"encounter_protocol.discharge_instructions", "encounter_protocol.follow_up"} <= set(facts)


def test_discharged_patient_gets_instructions_and_follow_up_ja() -> None:
    enc = _encounter(level="4", chief_complaint="裂傷（縫合が必要）")
    text, _ = build_ed_disposition(_GEN, _ctx("minor_laceration", "ja", encounter=enc))
    assert text.startswith("自宅退院（JTAS レベル 4、裂傷（縫合が必要））。")
    assert "。帰宅時指導: 24時間は創部を清潔・乾燥に保つ。" in text
    assert text.endswith("フォローアップ: 7〜10日後に抜糸（顔面は5日後）。")
    assert re.search(r"[A-Za-z]", text.replace("JTAS", "")) is None


def test_protocol_disposition_template_wraps_the_outcome_line() -> None:
    enc = _encounter(chief_complaint="Chest pain, rule out acute coronary syndrome")
    text, _ = build_ed_disposition(_GEN, _ctx("chest_pain_noncardiac", encounter=enc))
    assert text.startswith(
        "ACS ruled out with serial negative troponins and no ECG changes. Discharged home (ESI level 3, "
    )
    assert "Follow-up: primary care physician within 1 week." in text


@pytest.mark.parametrize("lang", ["en", "ja"])
def test_admitted_patient_keeps_the_admission_line_only(lang: str) -> None:
    enc = _encounter(encounter_type="inpatient", disposition="home", admission_datetime="2025-03-01T10:00:00")
    enc["encounter_type"] = "inpatient"
    text, facts = build_ed_disposition(_GEN, _ctx("minor_laceration", lang, encounter=enc))
    assert text.startswith("Admitted" if lang == "en" else "入院適応"), text
    assert "encounter_protocol.discharge_instructions" not in facts


def test_every_emergency_protocol_has_bilingual_instructions_and_follow_up() -> None:
    for cid, proto in _emergency_protocols().items():
        assert proto.get("discharge_instructions"), cid
        for lang in ("en", "ja"):
            text, _ = build_ed_disposition(_GEN, _ctx(cid, lang))
            assert ("Follow-up: " if lang == "en" else "フォローアップ: ") in text, (cid, text)


def test_emergency_protocol_rejects_single_language_instructions() -> None:
    raw = dict(load_encounter_condition("minor_laceration"))
    raw["discharge_instructions"] = ["Keep wound clean"]
    with pytest.raises(ValueError, match="needs en and ja"):
        EncounterConditionProtocol.model_validate(raw)
