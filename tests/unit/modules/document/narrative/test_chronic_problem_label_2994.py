"""Issue #2994: narratives name a chronic problem by the condition that is
coded in the output, not by the title of the internal disease-key category.

The internal dementia key is ICD-10 ``F00``; US output codes it as ICD-10-CM
``F03.90`` (unspecified dementia), so a US note must not call it
"Dementia in Alzheimer disease" (the ``F00`` category title).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from clinosim.modules.document.narrative.renderers._shared_helpers import chronic_condition_label
from clinosim.modules.document.narrative.renderers.section_builders.assessment_and_plan import (
    _compose_ap_assessment_from_state,
)
from clinosim.modules.document.narrative.renderers.section_builders.outpatient_soap import (
    _compose_chronic_condition_line,
    build_outpatient_assessment,
    build_outpatient_subjective,
)
from clinosim.modules.document.narrative.template_generator import TemplateNarrativeGenerator
from clinosim.types.document import DocumentType

pytestmark = pytest.mark.unit


def _ctx(lang: str, conditions: list, document_type: DocumentType = DocumentType.OUTPATIENT_SOAP):
    patient = SimpleNamespace(
        chronic_conditions=conditions, current_medications=[], age=81, sex="F", date_of_birth=None
    )
    return SimpleNamespace(
        patient=patient,
        encounter=SimpleNamespace(chief_complaint="Follow-up"),
        encounter_type=None,
        disease_protocol=None,
        encounter_protocol=None,
        clinical_course_archetype="",
        severity="moderate",
        day_index=0,
        los_days=0,
        vitals=[],
        lab_results=[],
        medications=[],
        diagnoses=[],
        procedures=[],
        allergies=[],
        document_type=document_type,
        target_lang=lang,
        locale="jp" if lang == "ja" else "us",
        materialized_facts=[],
        section_facts={},
        shift="",
        discharge_medications=[],
        working_diagnoses=[],
    )


_DEMENTIA = [SimpleNamespace(code="F00", stage="CDR 2"), SimpleNamespace(code="I10", stage="Stage 1")]


def test_label_follows_the_output_code() -> None:
    assert chronic_condition_label("F00", "US", "en") == "Dementia"
    assert chronic_condition_label("I10", "US", "en") == "Hypertension (HTN)"
    # JP output codes F00 itself (Alzheimer-type dementia), so it keeps that name.
    assert chronic_condition_label("F00", "JP", "ja") == "アルツハイマー型認知症"
    assert chronic_condition_label("E11.9", "JP", "ja") == "2型糖尿病"


def test_an_f03_90_patients_note_says_dementia_not_alzheimer() -> None:
    gen = TemplateNarrativeGenerator()
    ctx = _ctx("en", _DEMENTIA)
    texts = [
        build_outpatient_assessment(gen, ctx)[0],
        build_outpatient_subjective(gen, ctx)[0],
        _compose_chronic_condition_line(ctx),
    ]
    for text in texts:
        assert "Alzheimer" not in text, text
    assert any("Dementia" in text for text in texts)


def test_inpatient_assessment_backdrop_says_dementia() -> None:
    text = _compose_ap_assessment_from_state(_ctx("en", _DEMENTIA, DocumentType.ADMISSION_HP))
    assert "Alzheimer" not in text and "Dementia" in text


@pytest.mark.parametrize(
    ("lang", "label", "title"),
    [("en", "Dyslipidemia", "Disorders of lipoprotein"), ("ja", "脂質異常症", "リポタンパク")],
)
def test_family_history_names_a_relatives_condition_by_the_coded_condition(lang: str, label: str, title: str) -> None:
    from clinosim.modules.document.narrative.renderers.section_builders.patient_history import build_family_history

    ctx = _ctx(lang, [])
    ctx.locale = "jp" if lang == "ja" else "us"
    ctx.family_history = [{"relationship": "MTH", "deceased": False, "condition_codes": ["E78", "I10"]}]
    text, _ = build_family_history(TemplateNarrativeGenerator(), ctx)
    assert label in text and title not in text, text
