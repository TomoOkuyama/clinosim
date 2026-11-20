"""Template text records findings, never instructions (Issue #3251).

An ED HPI, an outpatient SOAP seed or an abnormal-vital item written as
"…を確認。" / "assess …" / "reviewed." reads as an unfinished checklist, and an
option list ("hand or arm") states neither the site nor the mechanism. The
guard covers every authored narrative text of the ED protocols and the two
outpatient SOAP reference files; the burn tests pin the resolution of the
option lists to one value drawn per encounter.
"""

from __future__ import annotations

import copy
import re
from pathlib import Path
from typing import Any

import pytest
import yaml

from clinosim.modules.document.narrative.renderers.section_builders.ed_note import build_ed_physical_exam
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
_DOC_REF = Path(__file__).resolve().parents[4].parent / "clinosim" / "modules" / "document" / "reference_data"

# An instruction to the reader: a "…を確認。" ending, "…評価要", "assess …",
# "evaluate for …", "… reviewed.", "review needed".
_INSTRUCTION = re.compile(
    r"(を確認(する)?[。.]?$|を聴取|を評価(する)?[。.]?$|評価要|精査要|確認する。|"
    r"\bassess\b|\bevaluate for\b|\b(?:was|were)?\s*reviewed\.|review needed|\bassessed\.)",
    re.IGNORECASE,
)
_NEGATION = re.compile(r"\b(no|not|without)\b|なし", re.IGNORECASE)
_OPTION_LIST = re.compile(r"(\b\w+ or \w+\b|[^\W\d_]または[^\W\d_])")


def _strings(node: Any) -> list[str]:
    if isinstance(node, str):
        return [node]
    if isinstance(node, dict):
        return [s for v in node.values() for s in _strings(v)]
    if isinstance(node, list):
        return [s for v in node for s in _strings(v)]
    return []


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.。])\s*", text) if s.strip()]


def _ed_hpis() -> list[tuple[str, str, str]]:
    out = []
    for cid, proto in load_all_encounter_conditions().items():
        tmpl = ((proto.get("narrative") or {}).get("ed_note_template")) or {}
        for lang, text in (tmpl.get("hpi") or {}).items():
            out.append((cid, lang, str(text)))
    return out


@pytest.mark.parametrize(("cid", "lang", "text"), _ed_hpis())
def test_ed_hpi_has_no_instruction_or_option_list(cid: str, lang: str, text: str) -> None:
    for sentence in _sentences(text):
        assert not _INSTRUCTION.search(sentence), f"{cid}/{lang}: instruction sentence {sentence!r}"
    for sentence in _sentences(text):
        if _NEGATION.search(sentence):
            continue  # "No fever, cough or rash" is a list of denied findings
        assert not _OPTION_LIST.search(sentence), f"{cid}/{lang}: option list in {sentence!r}"
    assert "〜" not in text or lang == "en", f"{cid}/{lang}: range of alternatives in {text!r}"


@pytest.mark.parametrize("name", ["chronic_soap_templates.yaml", "visit_reason_soap.yaml"])
def test_outpatient_soap_reference_has_no_instruction(name: str) -> None:
    data = yaml.safe_load((_DOC_REF / name).read_text(encoding="utf-8"))
    for text in _strings(data):
        for sentence in _sentences(text):
            assert not _INSTRUCTION.search(sentence), f"{name}: instruction sentence {sentence!r}"


def test_hedging_unconfirmed_control_is_not_an_instruction() -> None:
    data = yaml.safe_load((_DOC_REF / "hedging_phrases.yaml").read_text(encoding="utf-8"))
    for text in _strings(data["chronic_status"]):
        assert not _INSTRUCTION.search(text), text


# ── Burn HPI: one site, one mechanism and first aid ──────────────────────


def _burn_ctx(lang: str, enc_id: str, dx_code: str = "") -> NarrativeContext:
    encounter = {
        "encounter_id": enc_id,
        "encounter_type": "emergency",
        "chief_complaint": "Burn to hand/arm, partial thickness",
        "severity": "moderate",
        "discharge_disposition": "home",
        "triage_data": {"level": "4", "level_system": "ESI"},
    }
    return NarrativeContext(
        patient={"patient_id": "P1"},
        encounter=encounter,
        encounter_type="emergency",
        disease_protocol=None,
        encounter_protocol=load_encounter_condition("minor_burn"),
        clinical_course_archetype="",
        severity="moderate",
        day_index=0,
        los_days=1,
        vitals=[],
        lab_results=[],
        medications=[],
        diagnoses=[{"admission_diagnosis_code": dx_code}] if dx_code else [],
        procedures=[],
        allergies=[],
        document_type=DocumentType.ED_NOTE,
        target_lang=lang,
        locale="us" if lang == "en" else "jp",
    )


def test_burn_hpi_en_states_one_site_mechanism_and_first_aid() -> None:
    hpi, _ = build_hpi(_GEN, _burn_ctx("en", "ENC-B-1"))
    assert re.search(r"burn to the .*(hand|forearm)", hpi), hpi
    assert re.search(r"scald|hot pan|flame|hot oil", hpi), hpi
    assert re.search(r"cooled|covered", hpi), hpi
    assert "hand or" not in hpi and "reviewed" not in hpi and "{" not in hpi


def test_burn_hpi_ja_states_one_site_mechanism_and_first_aid() -> None:
    hpi, _ = build_hpi(_GEN, _burn_ctx("ja", "ENC-B-1"))
    assert re.search(r"(手|前腕)に熱傷", hpi), hpi
    assert re.search(r"熱湯|フライパン|炎|熱い油", hpi), hpi
    assert re.search(r"冷却|覆った", hpi), hpi
    assert "を確認。" not in hpi and "または" not in hpi and "{" not in hpi


def test_burn_hpi_is_drawn_per_encounter_and_repeatable() -> None:
    texts = {build_hpi(_GEN, _burn_ctx("en", f"ENC-B-{i}"))[0] for i in range(30)}
    assert len(texts) > 1
    assert build_hpi(_GEN, _burn_ctx("en", "ENC-B-7")) == build_hpi(_GEN, _burn_ctx("en", "ENC-B-7"))


@pytest.mark.parametrize(
    ("code", "lang", "pattern"),
    [
        ("T23.201A", "en", r"right hand"),
        ("T23.202A", "en", r"left hand"),
        ("T22.211A", "en", r"right forearm"),
        ("T22.212A", "en", r"left forearm"),
        ("T23.2", "ja", r"(右手背|左手掌)に熱傷"),
        ("T22.2", "ja", r"(右|左)前腕に熱傷"),
    ],
)
def test_burn_site_follows_the_coded_diagnosis(code: str, lang: str, pattern: str) -> None:
    """The HPI site is the site of the diagnosis variant the visit was coded
    with, not an independent draw (Issue #3251)."""
    for i in range(12):
        ctx = _burn_ctx(lang, f"ENC-B-{i}", code)
        hpi, _ = build_hpi(_GEN, ctx)
        assert re.search(pattern, hpi), (code, hpi)
        exam, _ = build_ed_physical_exam(_GEN, ctx)
        assert re.search(pattern.replace("に熱傷", ""), exam), (code, exam)


def test_keyed_variants_must_match_the_diagnosis_variants() -> None:
    proto = load_encounter_condition("minor_burn")
    data = copy.deepcopy(dict(proto))
    data["narrative"]["ed_note_template"]["variants"]["burn__site"]["en"].pop()
    data["narrative"]["ed_note_template"]["variants"]["burn__site"]["ja"].pop()
    with pytest.raises(ValueError, match="diagnosis_variants has 4"):
        EncounterConditionProtocol.model_validate(data)
    data = copy.deepcopy(dict(proto))
    data["diagnosis_variants"] = []
    data["icd10_code"] = "T30.0"
    with pytest.raises(ValueError, match="needs diagnosis_variants"):
        EncounterConditionProtocol.model_validate(data)
