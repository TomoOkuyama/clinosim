"""Issue #2875: documents of a stay that ended in death carry no discharge text.

A stay whose discharge disposition is ``exp`` keeps its nursing discharge
summary, but the summary records the death and post-mortem care instead of
"Discharge criteria met" and patient self-care teaching, in both languages.
The final days' progress notes do not speak of discharge preparation either.
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from typing import Any

import pytest

from clinosim.modules.document.narrative.registry import load_document_type_specs
from clinosim.modules.document.narrative.renderers._composers import pick_stable_progress_phrase
from clinosim.modules.document.narrative.template_generator import TemplateNarrativeGenerator
from clinosim.types.document import DocumentType, NarrativeContext
from clinosim.types.patient import PatientProfile

_DISCHARGE_TEXT = {
    "en": (
        "Discharge criteria met",
        "criteria met",
        "complete full antibiotic course",
        "early return",
        "discharge instructions",
        "discharge planning",
        "preparation for discharge",
        "planned discharge",
        "Discharge readiness confirmed",
    ),
    "ja": (
        "退院基準を満たし",
        "退院基準を満たす",
        "抗菌薬の内服完遂",
        "早期受診",
        "退院指導",
        "退院前日",
        "退院準備",
        "退院に向けた",
        "退院後生活指導",
    ),
}


def _ctx(disposition: str, lang: str, *, day_index: int = 5, los_days: int = 6) -> NarrativeContext:
    encounter = SimpleNamespace(
        encounter_id="enc-2875",
        encounter_type=SimpleNamespace(value="inpatient"),
        admission_datetime=datetime(2025, 3, 1, 10, 0),
        discharge_datetime=datetime(2025, 3, 6, 23, 40),
        discharge_disposition=disposition,
        chief_complaint="fever and cough",
        primary_nurse_id="",
    )
    patient = PatientProfile(patient_id="pt-2875")
    return NarrativeContext(
        patient=patient,
        encounter=encounter,
        encounter_type=SimpleNamespace(value="inpatient"),
        disease_protocol=SimpleNamespace(disease_id="bacterial_pneumonia"),
        encounter_protocol=None,
        clinical_course_archetype="uncomplicated_improvement",
        severity="severe",
        day_index=day_index,
        los_days=los_days,
        vitals=[],
        lab_results=[],
        medications=[],
        diagnoses=[],
        procedures=[],
        allergies=[],
        document_type=DocumentType.NURSING_DISCHARGE_SUMMARY,
        target_lang=lang,
        locale="jp" if lang == "ja" else "us",
    )


def _nursing_summary(disposition: str, lang: str) -> dict[str, Any]:
    spec = load_document_type_specs()[DocumentType.NURSING_DISCHARGE_SUMMARY]
    out = TemplateNarrativeGenerator().generate(_ctx(disposition, lang), spec)
    return out.sections


@pytest.mark.parametrize("lang", ["en", "ja"])
def test_nursing_summary_of_a_death_has_no_discharge_text(lang: str) -> None:
    sections = _nursing_summary("exp", lang)
    text = " ".join(sections.values())
    for phrase in _DISCHARGE_TEXT[lang]:
        assert phrase not in text, f"{phrase!r} in the nursing summary of an in-hospital death: {text!r}"


@pytest.mark.parametrize(
    ("lang", "death_marker"),
    [("en", "died in hospital"), ("ja", "死亡退院")],
)
def test_nursing_summary_of_a_death_records_the_death(lang: str, death_marker: str) -> None:
    sections = _nursing_summary("exp", lang)
    assert death_marker in sections["admission_status"]
    assert "2025-03-06 23:40" in sections["admission_status"]
    for key in ("patient_education", "discharge_readiness"):
        assert death_marker in sections[key] or "入院中死亡" in sections[key], sections[key]
    # Same four sections as a living discharge, each non-empty.
    assert set(sections) == set(_nursing_summary("home", lang))
    assert all(v.strip() for v in sections.values())


@pytest.mark.parametrize(("lang", "phrase"), [("en", "Discharge criteria met"), ("ja", "退院基準を満たし")])
def test_living_discharge_keeps_discharge_text(lang: str, phrase: str) -> None:
    sections = _nursing_summary("home", lang)
    assert phrase in sections["admission_status"]
    assert "完遂" in sections["patient_education"] or "antibiotic course" in sections["patient_education"]


@pytest.mark.parametrize("lang", ["en", "ja"])
@pytest.mark.parametrize("day_index", [4, 5])
def test_final_day_progress_phrase_of_a_death_has_no_discharge_text(lang: str, day_index: int) -> None:
    phrase = pick_stable_progress_phrase(_ctx("exp", lang, day_index=day_index), lang=lang)
    assert phrase
    for bad in _DISCHARGE_TEXT[lang]:
        assert bad not in phrase, f"{bad!r} in a final-day progress phrase of an in-hospital death"
