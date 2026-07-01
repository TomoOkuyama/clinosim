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
        display_en="Test spec",
        display_ja="テスト",
        format_type=FormatType.FREE_TEXT,
        countries_supported=("us", "jp"),
        generation_frequency="admission_once",
        encounter_types_supported=encounter_types_supported,
    )


# ---------------------------------------------------------------------------
# Test 1: existing α-min-1 specs get default encounter_types_supported = ()
# ---------------------------------------------------------------------------

def test_encounter_types_supported_default_empty_tuple() -> None:
    """Backwards-compat: α-min-1 specs without encounter_types_supported field → ()."""
    specs = load_document_type_specs()
    for dt in (DocumentType.ADMISSION_HP, DocumentType.PROGRESS_NOTE, DocumentType.DISCHARGE_SUMMARY):
        assert specs[dt].encounter_types_supported == (), (
            f"{dt.value} should have default encounter_types_supported=()"
        )


# ---------------------------------------------------------------------------
# Test 2: default () = no restriction → matches any encounter_type
# ---------------------------------------------------------------------------

def test_specs_for_encounter_type_empty_default_matches_inpatient() -> None:
    """Specs with encounter_types_supported=() match any encounter_type (no restriction)."""
    result = specs_for_encounter_type("inpatient")
    type_keys = [s.type_key for s in result]
    assert "admission_hp" in type_keys
    assert "progress_note" in type_keys
    assert "discharge_summary" in type_keys


def test_specs_for_encounter_type_empty_default_matches_outpatient() -> None:
    """Default () specs are returned even for outpatient (no restriction applies)."""
    result = specs_for_encounter_type("outpatient")
    type_keys = [s.type_key for s in result]
    assert "admission_hp" in type_keys


def test_specs_for_encounter_type_empty_default_matches_emergency() -> None:
    """Default () specs are returned even for emergency (no restriction applies).

    After α-min-2: 3 α-min-1 (no restriction) + 2 ED-specific = 5 total.
    """
    result = specs_for_encounter_type("emergency")
    type_keys = [s.type_key for s in result]
    # α-min-1 specs (no restriction) are always included regardless of encounter type
    assert "admission_hp" in type_keys
    assert "progress_note" in type_keys
    assert "discharge_summary" in type_keys
    # α-min-2 ED specs are also included for emergency
    assert "ed_note" in type_keys
    assert "ed_triage_note" in type_keys


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
