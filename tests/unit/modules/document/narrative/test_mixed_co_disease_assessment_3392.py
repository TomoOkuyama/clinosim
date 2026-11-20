"""Issue #3392: the admission assessment of a mixed admission names both
diseases, and the discharge diagnoses list the co-disease."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from clinosim.modules.document.narrative.passes import NarrativePass
from clinosim.modules.document.narrative.renderers.section_builders.assessment_and_plan import (
    _compose_ap_assessment_from_state,
)
from clinosim.modules.document.narrative.renderers.section_builders.discharge_summary import _secondary_diagnoses
from tests.unit.modules.document.narrative.test_admission_hp_exam_3245 import _ctx

pytestmark = pytest.mark.unit


def _mixed(lang: str):
    ctx = _ctx(None, lang, severity="severe")
    ctx.principal_disease_id = "hip_fracture"
    ctx.co_disease_ids = ["bacterial_pneumonia"]
    return ctx


def test_en_assessment_has_a_line_per_disease() -> None:
    text = _compose_ap_assessment_from_state(_mixed("en"))
    assert text.lower().count("severe") >= 1 and "moderate" in text.lower()
    assert "hip fracture" in text.lower() and "pneumonia" in text.lower(), text


def test_ja_assessment_has_a_line_per_disease_in_japanese() -> None:
    text = _compose_ap_assessment_from_state(_mixed("ja"))
    assert "肺炎" in text and "大腿骨" in text, text
    assert "bacterial_pneumonia" not in text and "hip_fracture" not in text


def test_a_single_disease_assessment_is_unchanged() -> None:
    ctx = _ctx("bacterial_pneumonia", "en")
    assert _compose_ap_assessment_from_state(ctx).lower().count("pneumonia") == 1


def test_the_co_disease_ids_come_from_the_ground_truth_of_a_mixed_event() -> None:
    mixed = SimpleNamespace(condition_type="mixed", ground_truth_diseases=["hip_fracture", "bacterial_pneumonia"])
    known = SimpleNamespace(condition_type="known_disease", ground_truth_diseases=["hip_fracture"])
    assert NarrativePass._co_disease_ids(mixed) == ["bacterial_pneumonia"]
    assert NarrativePass._co_disease_ids(known) == []


@pytest.mark.parametrize(("lang", "needle"), [("en", "pneumonia"), ("ja", "肺炎")])
def test_discharge_diagnoses_list_the_co_disease(lang: str, needle: str) -> None:
    ctx = _ctx(None, lang)
    ctx.locale = "JP" if lang == "ja" else "US"
    dx = SimpleNamespace(
        discharge_diagnosis_code="S72.00", admission_diagnosis_code="S72.0", secondary_diagnosis_codes=["J18.9"]
    )
    items = _secondary_diagnoses(ctx, [dx])
    assert len(items) == 1 and needle in items[0].lower() and "J18.9" in items[0], items
