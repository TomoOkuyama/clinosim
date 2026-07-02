"""DocumentTypeSpec.encounter_types_supported gating tests (Task 7)."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from clinosim.modules.document.narrative.registry import (
    DocumentTypeSpec,
    load_document_type_specs,
    specs_for_encounter_type,
)
from clinosim.types.document import DocumentType, FormatType


# ---------------------------------------------------------------------------
# Helper factory — construct a minimal DocumentTypeSpec with encounter_types_supported
# ---------------------------------------------------------------------------

def _make_spec(type_key: str, encounter_types_supported: tuple[str, ...] = ()) -> DocumentTypeSpec:
    return DocumentTypeSpec(
        type_key=type_key,
        loinc_code="99999-9",
        format_type=FormatType.FREE_TEXT,
        countries_supported=("us", "jp"),
        generation_frequency="admission_once",
        encounter_types_supported=encounter_types_supported,
    )


# ---------------------------------------------------------------------------
# Test 1: α-min-1 specs have explicit inpatient/icu/rehab_inpatient gating (Task 10 fix)
# ---------------------------------------------------------------------------

def test_encounter_types_supported_alpha_min1_specs_explicit_inpatient() -> None:
    """Task 10 data-quality fix: α-min-1 specs now carry explicit encounter_types_supported
    = ('inpatient', 'icu', 'rehab_inpatient') to prevent leaking into outpatient/emergency.
    """
    specs = load_document_type_specs()
    expected = frozenset({"inpatient", "icu", "rehab_inpatient"})
    for dt in (DocumentType.ADMISSION_HP, DocumentType.PROGRESS_NOTE, DocumentType.DISCHARGE_SUMMARY):
        actual = frozenset(specs[dt].encounter_types_supported)
        assert actual == expected, (
            f"{dt.value} encounter_types_supported must be {expected}, got {actual}"
        )


# ---------------------------------------------------------------------------
# Test 2: encounter-type gating returns correct specs per encounter type
# ---------------------------------------------------------------------------

def test_specs_for_encounter_type_inpatient_returns_inpatient_specs() -> None:
    """inpatient → α-min-1 specs + nursing specs; NOT outpatient/ED specs."""
    result = specs_for_encounter_type("inpatient")
    type_keys = [s.type_key for s in result]
    assert "admission_hp" in type_keys
    assert "progress_note" in type_keys
    assert "discharge_summary" in type_keys
    assert "admission_nursing_assessment" in type_keys
    # outpatient/ED specs must NOT appear for inpatient
    assert "outpatient_soap" not in type_keys
    assert "ed_note" not in type_keys
    assert "ed_triage_note" not in type_keys


def test_specs_for_encounter_type_outpatient_excludes_inpatient_specs() -> None:
    """outpatient → OUTPATIENT_SOAP only; NO α-min-1 inpatient or ED specs."""
    result = specs_for_encounter_type("outpatient")
    type_keys = [s.type_key for s in result]
    # outpatient spec
    assert "outpatient_soap" in type_keys
    # inpatient/nursing specs must not leak into outpatient
    assert "admission_hp" not in type_keys
    assert "progress_note" not in type_keys
    assert "discharge_summary" not in type_keys
    assert "admission_nursing_assessment" not in type_keys
    # ED specs also excluded
    assert "ed_note" not in type_keys
    assert "ed_triage_note" not in type_keys


def test_specs_for_encounter_type_emergency_returns_ed_specs_only() -> None:
    """emergency → ED_NOTE + ED_TRIAGE_NOTE; NO inpatient or outpatient specs."""
    result = specs_for_encounter_type("emergency")
    type_keys = [s.type_key for s in result]
    # ED specs included
    assert "ed_note" in type_keys
    assert "ed_triage_note" in type_keys
    # inpatient specs excluded (Task 10 fix: explicit encounter_types_supported)
    assert "admission_hp" not in type_keys
    assert "progress_note" not in type_keys
    assert "discharge_summary" not in type_keys
    # outpatient spec excluded
    assert "outpatient_soap" not in type_keys


# ---------------------------------------------------------------------------
# Test 3: explicit gating — match hit
# ---------------------------------------------------------------------------

def test_specs_for_encounter_type_explicit_gating_hit() -> None:
    """Spec with encounter_types_supported=('outpatient',) IS returned for 'outpatient'."""
    outpatient_spec = _make_spec("outpatient_note", ("outpatient",))
    mock_specs = {DocumentType.ADMISSION_HP: outpatient_spec}
    with patch(
        "clinosim.modules.document.narrative.registry.load_document_type_specs",
        return_value=mock_specs,
    ):
        result = specs_for_encounter_type("outpatient")
    assert len(result) == 1
    assert result[0].type_key == "outpatient_note"


# ---------------------------------------------------------------------------
# Test 4: explicit gating — miss
# ---------------------------------------------------------------------------

def test_specs_for_encounter_type_explicit_gating_miss() -> None:
    """Spec with encounter_types_supported=('outpatient',) is NOT returned for 'inpatient'."""
    outpatient_spec = _make_spec("outpatient_note", ("outpatient",))
    mock_specs = {DocumentType.ADMISSION_HP: outpatient_spec}
    with patch(
        "clinosim.modules.document.narrative.registry.load_document_type_specs",
        return_value=mock_specs,
    ):
        result = specs_for_encounter_type("inpatient")
    assert result == []


# ---------------------------------------------------------------------------
# Test 5: mixed — some restricted, some unrestricted
# ---------------------------------------------------------------------------

def test_specs_for_encounter_type_mixed_default_and_explicit() -> None:
    """Unrestricted () spec + restricted spec → restricted one filtered out for wrong type."""
    unrestricted = _make_spec("admission_hp", ())
    restricted = _make_spec("outpatient_note", ("outpatient",))
    mock_specs = {
        DocumentType.ADMISSION_HP: unrestricted,
        DocumentType.PROGRESS_NOTE: restricted,
    }
    with patch(
        "clinosim.modules.document.narrative.registry.load_document_type_specs",
        return_value=mock_specs,
    ):
        result = specs_for_encounter_type("inpatient")
    type_keys = [s.type_key for s in result]
    assert "admission_hp" in type_keys      # unrestricted → always included
    assert "outpatient_note" not in type_keys  # restricted to outpatient → excluded


# ---------------------------------------------------------------------------
# Test 6: case-insensitive matching on encounter_type input
# ---------------------------------------------------------------------------

def test_specs_for_encounter_type_case_insensitive_input() -> None:
    """'INPATIENT' and 'Inpatient' both match spec.encounter_types_supported=('inpatient',)."""
    inpatient_spec = _make_spec("admission_note", ("inpatient",))
    mock_specs = {DocumentType.ADMISSION_HP: inpatient_spec}
    with patch(
        "clinosim.modules.document.narrative.registry.load_document_type_specs",
        return_value=mock_specs,
    ):
        for variant in ("INPATIENT", "Inpatient", "InPatient"):
            result = specs_for_encounter_type(variant)
            assert len(result) == 1, f"Case variant {variant!r} should match"


# ---------------------------------------------------------------------------
# Test 7: multiple encounter_types in a single spec
# ---------------------------------------------------------------------------

def test_specs_for_encounter_type_multi_type_spec() -> None:
    """Spec covering ('inpatient', 'emergency') matches both but not 'outpatient'."""
    multi_spec = _make_spec("acute_note", ("inpatient", "emergency"))
    mock_specs = {DocumentType.ADMISSION_HP: multi_spec}
    with patch(
        "clinosim.modules.document.narrative.registry.load_document_type_specs",
        return_value=mock_specs,
    ):
        assert len(specs_for_encounter_type("inpatient")) == 1
        assert len(specs_for_encounter_type("emergency")) == 1
        assert specs_for_encounter_type("outpatient") == []


# ---------------------------------------------------------------------------
# Test 8: re-export from document __init__
# ---------------------------------------------------------------------------

def test_specs_for_encounter_type_importable_from_module_init() -> None:
    """specs_for_encounter_type is importable from clinosim.modules.document."""
    from clinosim.modules.document import specs_for_encounter_type as fn  # noqa: F401

    assert callable(fn)
