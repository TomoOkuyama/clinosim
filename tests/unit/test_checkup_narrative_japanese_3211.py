"""The JP health-checkup questionnaire narrative reads as Japanese (Issue
#3211): drug names from the drug catalog, lifestyle labels in Japanese, and
no raw category key."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from clinosim.modules.document.narrative.renderers.section_builders.jp_clins import build_checkup_questionnaire
from clinosim.modules.document.narrative.template_generator import TemplateNarrativeGenerator
from clinosim.types.document import DocumentType, NarrativeContext
from clinosim.types.patient import HomeMedication

pytestmark = pytest.mark.unit


def _text(lang: str = "ja", **patient: object) -> str:
    pt = {
        "patient_id": "P1",
        "chronic_conditions": [],
        "current_medications": [],
        "smoking_status": "never",
        "alcohol_use": "none",
    }
    pt.update(patient)
    ctx = NarrativeContext(
        patient=SimpleNamespace(**pt),
        encounter=SimpleNamespace(encounter_id="CHK-1", admission_datetime="2026-08-03T09:00:00"),
        encounter_type=None,
        disease_protocol=None,
        encounter_protocol=None,
        clinical_course_archetype="",
        severity="",
        day_index=0,
        los_days=1,
        vitals=[],
        lab_results=[],
        medications=[],
        diagnoses=[],
        procedures=[],
        allergies=[],
        document_type=DocumentType("health_checkup_report"),
        target_lang=lang,
        locale="jp" if lang == "ja" else "us",
    )
    text, _ = build_checkup_questionnaire(TemplateNarrativeGenerator(), ctx)
    return text


def _line(text: str, header: str) -> str:
    return next(line for line in text.splitlines() if line.startswith(header))


def test_medications_are_written_with_their_japanese_names() -> None:
    meds = [
        HomeMedication(drug_name="Spironolactone", drug_name_ja="スピロノラクトン"),
        HomeMedication(drug_name="Amlodipine"),  # no stored JA name: the catalog's
    ]
    line = _line(_text(current_medications=meds), "【服薬】")
    assert line == "【服薬】スピロノラクトン、アムロジピン。"


def test_a_social_drinker_is_written_in_japanese() -> None:
    assert _line(_text(alcohol_use="social"), "【生活習慣】") == "【生活習慣】喫煙歴なし、機会飲酒。"


def test_an_unlabelled_lifestyle_value_is_omitted_not_shown_raw() -> None:
    text = _text(smoking_status="current", alcohol_use="binge")
    assert _line(text, "【生活習慣】") == "【生活習慣】現在喫煙中。"
    assert "区分未定義" not in text and "binge" not in text


def test_the_english_report_keeps_its_wording() -> None:
    text = _text("en", alcohol_use="social", current_medications=[HomeMedication(drug_name="Amlodipine")])
    assert "Lifestyle: smoking=never, alcohol=social." in text
    assert "Medications: Amlodipine." in text
