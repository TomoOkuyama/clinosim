"""Issue #3558: the HPI negatives and onset never contradict the record.

A "no fever" is not written next to a febrile arrival temperature, the MI
ROS has no exertion-only chest-pain negative, an onset the chief complaint
already gives is not repeated differently, and the severity filler is not
written where an onset sentence exists."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from clinosim.modules.disease.protocol import load_disease_protocol
from clinosim.modules.document.narrative.context import build_narrative_context
from clinosim.modules.document.narrative.renderers.section_builders.chief_complaint import (
    chief_complaint_states_onset,
    encounter_chief_complaint,
)
from clinosim.modules.document.narrative.renderers.section_builders.hpi import _ros_line, build_hpi
from clinosim.modules.document.narrative.template_generator import TemplateNarrativeGenerator
from clinosim.modules.document.reference_data_loaders import (
    hpi_pertinent_negatives,
    load_chief_complaint_variant_rules,
    load_hpi_pertinent_negatives,
)
from clinosim.types.document import DocumentType

pytestmark = pytest.mark.unit

_REPO = Path(__file__).resolve().parents[4]


def _ctx(country: str, disease: str | None, *, temp: float | None = None, cc: str = "", enc_id: str = "E-3558"):
    vitals = [{"temperature_celsius": temp, "heart_rate": 80}] if temp is not None else []
    encounter = {
        "encounter_id": enc_id,
        "encounter_type": "inpatient",
        "admission_datetime": "2026-06-21T10:00:00",
        "chief_complaint": cc,
        "chief_complaint_ja": cc,
    }
    record = {
        "patient": {
            "patient_id": "P-3558",
            "age": 70,
            "sex": "M",
            "date_of_birth": "1956-01-01",
            "current_medications": [],
            "chronic_conditions": [],
        },
        "encounters": [encounter],
        "vital_signs": vitals,
    }
    ctx = build_narrative_context(record, encounter, DocumentType.ADMISSION_HP, 0, country)
    ctx.disease_protocol = load_disease_protocol(disease) if disease else None
    return ctx


@pytest.mark.parametrize(("country", "phrase"), [("US", "no fever"), ("JP", "発熱なし")])
@pytest.mark.parametrize("temp", [37.5, 38.5])
def test_febrile_arrival_drops_the_fever_negative(country: str, phrase: str, temp: float) -> None:
    assert phrase not in _ros_line(_ctx(country, "diabetic_ketoacidosis", temp=temp), "")


@pytest.mark.parametrize(("country", "phrase"), [("US", "no fever"), ("JP", "発熱なし")])
def test_afebrile_arrival_keeps_the_fever_negative(country: str, phrase: str) -> None:
    assert phrase in _ros_line(_ctx(country, "diabetic_ketoacidosis", temp=36.8), "")
    assert phrase in _ros_line(_ctx(country, "diabetic_ketoacidosis"), "")


def test_every_fever_negative_lists_the_fever_rule() -> None:
    for disease, entries in load_hpi_pertinent_negatives().items():
        for entry in entries:
            if any(re.search(r"fever|発熱", text, re.I) for text in entry.text.values()):
                assert "fever_present" in entry.contradicted_by, (disease, entry.text)


def test_mi_has_no_exertion_only_chest_pain_negative() -> None:
    for lang in ("en", "ja"):
        for neg in hpi_pertinent_negatives("acute_mi", lang):
            assert "exertion" not in neg.text and "労作時以外" not in neg.text, neg.text


def test_encounter_hpi_texts_deny_no_fever() -> None:
    """The fixed ED HPI texts do not deny a fever the visit's own vitals may show."""
    for path in (_REPO / "clinosim/modules/encounter/reference_data").glob("*.yaml"):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        hpi = (((data.get("narrative") or {}).get("ed_note_template") or {}).get("hpi")) or {}
        for text in hpi.values():
            assert not re.search(r"No fever|no fever|発熱なし|発熱・", str(text)), (path.name, text)


def _jp_variant_ctx(disease: str, variant_text: str):
    for i in range(400):
        ctx = _ctx("JP", disease, cc=_canonical(disease), enc_id=f"E-3558-{i}")
        if encounter_chief_complaint(ctx) == variant_text:
            return ctx
    raise AssertionError(f"variant {variant_text!r} never picked")


def _canonical(disease: str) -> str:
    proto = load_disease_protocol(disease)
    cc = proto.chief_complaint
    return str(cc.get("ja") if isinstance(cc, dict) else cc)


def test_a_complaint_that_states_its_onset_gets_no_second_onset() -> None:
    ctx = _jp_variant_ctx("copd_exacerbation", "1週間前より痰の量と粘稠度が増加")
    assert chief_complaint_states_onset(ctx)
    text, _ = build_hpi(TemplateNarrativeGenerator(), ctx)
    assert "1週間前より痰の量と粘稠度が増加" in text
    assert "数日前" not in text and "数週間前" not in text, text


def test_a_complaint_without_onset_keeps_the_onset_sentence() -> None:
    ctx = _ctx("JP", "copd_exacerbation", cc=_canonical("copd_exacerbation"))
    ctx_text, _ = build_hpi(TemplateNarrativeGenerator(), ctx)
    assert not chief_complaint_states_onset(ctx) or "数" not in ctx_text
    plain = _ctx("JP", "copd_exacerbation", cc="呼吸困難")
    assert not chief_complaint_states_onset(plain)


_DURATION = re.compile(r"\d+\s*(日|週間|時間|か月|ヶ月)|本日|昨夜|朝|日目")


def test_every_variant_that_states_a_duration_is_marked() -> None:
    for pool, variants in load_chief_complaint_variant_rules().items():
        for v in variants:
            if _DURATION.search(v.text):
                assert v.onset_stated, (pool, v.text)


def test_ankle_sprain_complaint_does_not_claim_a_weight_bearing_state() -> None:
    assert all("荷重" not in v.text for v in load_chief_complaint_variant_rules()["ankle_sprain"])


@pytest.mark.parametrize(("country", "marker"), [("US", "Symptoms began"), ("JP", "突然")])
def test_principal_disease_onset_replaces_the_severity_filler(country: str, marker: str) -> None:
    ctx = _ctx(country, None, cc="Chest pain" if country == "US" else "胸痛")
    ctx.principal_disease_id = "acute_mi"
    ctx.severity = "severe"
    text, _ = build_hpi(TemplateNarrativeGenerator(), ctx)
    assert marker in text, text
    assert "severe symptoms" not in text and "重度の症状" not in text


@pytest.mark.parametrize("country", ["US", "JP"])
def test_no_filler_when_a_complaint_exists_and_no_onset_is_known(country: str) -> None:
    ctx = _ctx(country, None, cc="Chest pain" if country == "US" else "胸痛")
    ctx.severity = "severe"
    text, _ = build_hpi(TemplateNarrativeGenerator(), ctx)
    assert "severe symptoms" not in text and "重度の症状" not in text and "重症の症状" not in text, text
