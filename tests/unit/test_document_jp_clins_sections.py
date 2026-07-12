"""P2-13 PR2a Task 2: JP-CLINS discharge summary section list selector."""

from __future__ import annotations

import pytest

from clinosim.modules.document.narrative.registry import load_document_type_specs
from clinosim.types.document import DocumentType


@pytest.mark.unit
def test_discharge_summary_us_sections_unchanged():
    spec = load_document_type_specs()[DocumentType("discharge_summary")]
    assert spec.composition_sections_for("US") == (
        "admission_summary",
        "hospital_course",
        "discharge_diagnoses",
        "discharge_medications",
        "discharge_instructions",
        "follow_up",
    )


@pytest.mark.unit
def test_discharge_summary_jp_sections_are_5_required():
    spec = load_document_type_specs()[DocumentType("discharge_summary")]
    assert spec.composition_sections_for("JP") == (
        "admission_reason",
        "admission_details",
        "admission_diagnoses",
        "chief_complaint",
        "present_illness",
    )


@pytest.mark.unit
def test_non_discharge_spec_no_jp_override():
    """Only discharge_summary has composition_sections_jp populated (for now)."""
    for _, spec in load_document_type_specs().items():
        if spec.type_key == "discharge_summary":
            continue
        # JP call falls through to composition_sections when no _jp override.
        assert spec.composition_sections_for("JP") == spec.composition_sections
        assert spec.composition_sections_for("US") == spec.composition_sections
