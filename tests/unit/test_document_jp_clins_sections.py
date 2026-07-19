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
def test_discharge_summary_jp_sections_are_10_required():
    """#286: JP-CLINS eDS spec pins `structuredSection.section` min=10.
    Session 58 Chain #9 added the 5 discharge-side slice codes to
    `_JP_DS_SECTION_CODE`; session 59 #286 mirrors the extension in the
    document type spec so the narrative pass produces text for all 10
    slices and `txt-2` (non-whitespace text.div) is not violated.
    """
    spec = load_document_type_specs()[DocumentType("discharge_summary")]
    assert spec.composition_sections_for("JP") == (
        # Admission side (5)
        "admission_reason",
        "admission_details",
        "admission_diagnoses",
        "chief_complaint",
        "present_illness",
        # Discharge side (5, session 59 #286)
        "hospital_course",
        "discharge_details",
        "discharge_diagnoses",
        "discharge_medications",
        "discharge_instructions",
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
