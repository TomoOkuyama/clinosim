"""Issue #3228: the Japanese HPI reads as one coherent narrative —
demographics and chief complaint first, then one onset sentence that agrees
with the mechanism, then history, medications and pertinent negatives that
never deny a symptom of the chief complaint. The ED HPI does not restate the
demographics and chief complaint after its authored narrative."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from clinosim.modules.disease.protocol import load_disease_protocol
from clinosim.modules.document.narrative.context import build_narrative_context
from clinosim.modules.document.narrative.renderers.section_builders.chief_complaint import build_chief_complaint
from clinosim.modules.document.narrative.renderers.section_builders.hpi import build_hpi
from clinosim.modules.document.narrative.template_generator import TemplateNarrativeGenerator
from clinosim.modules.document.reference_data_loaders import hpi_pertinent_negatives
from clinosim.modules.encounter.protocol import load_encounter_condition
from clinosim.types.document import DocumentType, NarrativeContext

pytestmark = pytest.mark.unit

_DISEASE_DIR = Path(__file__).resolve().parents[2] / "clinosim" / "modules" / "disease" / "reference_data"
_GRADUAL = ("緩徐", "漸次", "数日前", "数週間前")
_ACUTE = ("急性発症", "突然発症")


def _record(chief_complaint: str, encounter_type: str = "inpatient", age: int = 68) -> dict:
    return {
        "patient": {
            "patient_id": "POP-3228",
            "age": age,
            "sex": "M",
            "current_medications": [],
            "chronic_conditions": [],
        },
        "encounters": [
            {
                "encounter_id": "ENC-3228",
                "encounter_type": encounter_type,
                "admission_datetime": "2026-06-21T10:00:00",
                "chief_complaint": chief_complaint,
            }
        ],
    }


def _ctx(
    disease_id: str | None,
    chief_complaint: str,
    severity: str = "moderate",
    doc_type: DocumentType = DocumentType.ADMISSION_HP,
    age: int = 68,
) -> NarrativeContext:
    enc_type = "emergency" if doc_type == DocumentType.ED_NOTE else "inpatient"
    record = _record(chief_complaint, enc_type, age)
    ctx = build_narrative_context(record, record["encounters"][0], doc_type, 0, "JP")
    ctx.disease_protocol = load_disease_protocol(disease_id) if disease_id else None
    ctx.severity = severity
    if doc_type == DocumentType.ED_NOTE:
        ctx.encounter_protocol = load_encounter_condition("renal_colic")
    return ctx


def _hpi(
    disease_id: str | None,
    chief_complaint: str,
    severity: str = "moderate",
    doc_type: DocumentType = DocumentType.ADMISSION_HP,
    age: int = 68,
) -> str:
    return build_hpi(TemplateNarrativeGenerator(), _ctx(disease_id, chief_complaint, severity, doc_type, age))[0]


@pytest.mark.parametrize("encounter_id", [f"ENC-3228-{i}" for i in range(8)])
def test_the_hpi_names_the_complaint_the_chief_complaint_section_shows(encounter_id: str) -> None:
    # The UTI default complaint is shown as a per-encounter variant (Issue #983).
    ctx = _ctx("urinary_tract_infection", "発熱・排尿時痛・側腹部痛")
    ctx.encounter["encounter_id"] = encounter_id
    gen = TemplateNarrativeGenerator()
    cc = build_chief_complaint(gen, ctx)[0]
    text = build_hpi(gen, ctx)[0]
    assert f"主訴: {cc}。" in text, (cc, text)
    ros = re.search(r"ROS: (.*?)。", text)
    for item in ros.group(1).split("、") if ros else []:
        assert item.removesuffix("なし") not in cc, (cc, text)


def test_a_negative_never_denies_a_symptom_of_the_chief_complaint() -> None:
    text = _hpi("urinary_tract_infection", "発熱・側腹部痛")
    assert "側腹部痛なし" not in text
    assert "ROS: 血尿なし、嘔吐なし。" in text


def test_a_negative_unrelated_to_the_complaint_is_kept() -> None:
    assert "ROS: 側腹部痛なし、血尿なし。" in _hpi("urinary_tract_infection", "発熱・排尿時痛")


def test_a_negated_complaint_term_does_not_filter_the_negative() -> None:
    assert "側腹部痛なし" in _hpi("urinary_tract_infection", "排尿時痛、側腹部痛なし")


@pytest.mark.parametrize("severity", ["mild", "moderate", "severe"])
def test_a_fall_fracture_has_one_injury_onset(severity: str) -> None:
    text = _hpi("hip_fracture", "転倒後の股関節痛・歩行不能", severity)
    assert "受傷" in text
    assert not any(w in text for w in _GRADUAL), text
    assert not any(w in text for w in _ACUTE), text


def test_demographics_and_complaint_come_before_the_onset() -> None:
    text = _hpi("urinary_tract_infection", "発熱・排尿時痛")
    assert text.startswith("68歳男性患者。主訴: 発熱・排尿時痛。症状は数日前より出現し漸次増悪。"), text


def test_an_authored_trigger_is_a_sentence_after_the_onset() -> None:
    text = _hpi("bacterial_pneumonia", "発熱・咳嗽")
    assert "緊急受診。上気道感染後に発症。" in text, text
    assert not re.search(r"[^\d。] ?\d+歳", text), text


def test_no_leading_presented_fragment_when_other_content_follows() -> None:
    text = _hpi(None, "新生児 — 院内出生", severity="", age=0)
    assert "受診となった" not in text
    assert text.startswith("主訴: 新生児 — 院内出生。"), text


def test_the_ed_hpi_does_not_restate_the_complaint_after_its_narrative() -> None:
    text = _hpi(None, "右側腹部痛", doc_type=DocumentType.ED_NOTE)
    assert "主訴" not in text
    assert text.startswith("68歳男性患者。"), text
    assert "疝痛" in text


@pytest.mark.parametrize("path", sorted(_DISEASE_DIR.glob("*.yaml")), ids=lambda p: p.stem)
def test_every_hpi_template_has_an_onset_type_and_no_onset_token_trigger(path: Path) -> None:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    tmpl = (data.get("narrative") or {}).get("hpi_template")
    if not tmpl:
        pytest.skip("no hpi_template")
    assert tmpl.get("onset_type"), path.stem
    for trig in tmpl.get("trigger_options") or []:
        assert not any(w in trig for w in _ACUTE), (path.stem, trig)
    for text in (tmpl.get("onset_pattern") or {}).values():
        assert not (any(w in text for w in _GRADUAL) and any(w in text for w in _ACUTE)), (path.stem, text)


def test_negatives_carry_the_symptom_terms_they_deny() -> None:
    neg = hpi_pertinent_negatives("urinary_tract_infection", "ja")[0]
    assert neg.text == "側腹部痛なし"
    assert "側腹部痛" in neg.symptoms
    assert hpi_pertinent_negatives("urinary_tract_infection", "fr")[0].symptoms[0] == "flank pain"
