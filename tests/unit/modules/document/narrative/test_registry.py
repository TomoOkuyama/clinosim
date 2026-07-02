"""DocumentTypeSpec registry tests."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from clinosim.modules.document.narrative.registry import (
    SUPPORTED_DOCUMENT_TYPES,
    DocumentTypeSpec,
    load_document_type_specs,
    specs_for_country,
    specs_for_encounter_type,
)
from clinosim.types.document import DocumentType, FormatType


def test_registry_covers_α_min_1_doc_types() -> None:
    specs = load_document_type_specs()
    assert DocumentType.ADMISSION_HP in specs
    assert DocumentType.PROGRESS_NOTE in specs
    assert DocumentType.DISCHARGE_SUMMARY in specs


def test_admission_hp_spec_metadata() -> None:
    specs = load_document_type_specs()
    hp = specs[DocumentType.ADMISSION_HP]
    assert hp.loinc_code == "34117-2"
    assert hp.format_type == FormatType.COMPOSITION
    assert "us" in hp.countries_supported
    assert "jp" in hp.countries_supported


def test_progress_note_is_free_text() -> None:
    specs = load_document_type_specs()
    pn = specs[DocumentType.PROGRESS_NOTE]
    assert pn.format_type == FormatType.FREE_TEXT


def test_country_gating_for_us() -> None:
    us_specs = specs_for_country("us")
    types = [s.type_key for s in us_specs]
    assert "admission_hp" in types
    assert "progress_note" in types
    assert "discharge_summary" in types
    # JP-only docs(後続 phase で追加)はこの時点では未登録、フィルタ対象なし


def test_country_gating_unknown_returns_empty() -> None:
    result = specs_for_country("xx")
    assert result == []


def test_discharge_summary_spec_metadata() -> None:
    specs = load_document_type_specs()
    ds = specs[DocumentType.DISCHARGE_SUMMARY]
    assert ds.loinc_code == "18842-5"
    assert ds.format_type == FormatType.COMPOSITION
    assert "hospital_course" in ds.composition_sections


def test_load_raises_on_missing_required_field() -> None:
    """6-layer validator fires on missing required field."""
    import clinosim.modules.document.narrative.registry as reg_module

    bad_data = {
        "specs": {
            "admission_hp": {
                "loinc_code": "34117-2",
                "format_type": "composition",
                # countries_supported intentionally missing
                "generation_frequency": "admission_once",
            },
            "progress_note": {
                "loinc_code": "11506-3",
                "format_type": "free_text",
                "countries_supported": ["us", "jp"],
                "generation_frequency": "daily",
            },
            "discharge_summary": {
                "loinc_code": "18842-5",
                "format_type": "composition",
                "countries_supported": ["us", "jp"],
                "generation_frequency": "discharge_once",
            },
            "admission_nursing_assessment": {
                "loinc_code": "78390-2",
                "format_type": "composition",
                "countries_supported": ["us", "jp"],
                "generation_frequency": "admission_once",
            },
            "nursing_shift_note": {
                "loinc_code": "34746-8",
                "format_type": "free_text",
                "countries_supported": ["us", "jp"],
                "generation_frequency": "daily",
            },
            "nursing_discharge_summary": {
                "loinc_code": "34745-0",
                "format_type": "composition",
                "countries_supported": ["us", "jp"],
                "generation_frequency": "discharge_once",
            },
            "outpatient_soap": {
                "loinc_code": "34131-3",
                "format_type": "composition",
                "countries_supported": ["us", "jp"],
                "generation_frequency": "encounter_once",
            },
            "ed_note": {
                "loinc_code": "34878-9",
                "format_type": "composition",
                "countries_supported": ["us", "jp"],
                "generation_frequency": "encounter_once",
            },
            "ed_triage_note": {
                "loinc_code": "54094-8",
                "format_type": "free_text",
                "countries_supported": ["us", "jp"],
                "generation_frequency": "encounter_once",
            },
        }
    }
    with pytest.raises(ValueError, match="missing countries_supported"):
        reg_module._validate_document_type_specs(bad_data)


def test_load_raises_on_null_entry() -> None:
    """6-layer validator Layer 3: per-bucket null entry raises ValueError."""
    import clinosim.modules.document.narrative.registry as reg_module

    bad_data = {
        "specs": {
            "admission_hp": None,  # null entry
            "progress_note": {
                "loinc_code": "11506-3",
                "format_type": "free_text",
                "countries_supported": ["us", "jp"],
                "generation_frequency": "daily",
            },
            "discharge_summary": {
                "loinc_code": "18842-5",
                "format_type": "composition",
                "countries_supported": ["us", "jp"],
                "generation_frequency": "discharge_once",
            },
            "admission_nursing_assessment": {
                "loinc_code": "78390-2",
                "format_type": "composition",
                "countries_supported": ["us", "jp"],
                "generation_frequency": "admission_once",
            },
            "nursing_shift_note": {
                "loinc_code": "34746-8",
                "format_type": "free_text",
                "countries_supported": ["us", "jp"],
                "generation_frequency": "daily",
            },
            "nursing_discharge_summary": {
                "loinc_code": "34745-0",
                "format_type": "composition",
                "countries_supported": ["us", "jp"],
                "generation_frequency": "discharge_once",
            },
            "outpatient_soap": {
                "loinc_code": "34131-3",
                "format_type": "composition",
                "countries_supported": ["us", "jp"],
                "generation_frequency": "encounter_once",
            },
            "ed_note": {
                "loinc_code": "34878-9",
                "format_type": "composition",
                "countries_supported": ["us", "jp"],
                "generation_frequency": "encounter_once",
            },
            "ed_triage_note": {
                "loinc_code": "54094-8",
                "format_type": "free_text",
                "countries_supported": ["us", "jp"],
                "generation_frequency": "encounter_once",
            },
        }
    }
    with pytest.raises(ValueError, match="admission_hp.*empty entry"):
        reg_module._validate_document_type_specs(bad_data)


def test_load_raises_on_empty_countries_supported() -> None:
    """6-layer validator fires on empty countries_supported list."""
    import clinosim.modules.document.narrative.registry as reg_module

    bad_data = {
        "specs": {
            "admission_hp": {
                "loinc_code": "34117-2",
                "format_type": "composition",
                "countries_supported": [],  # empty
                "generation_frequency": "admission_once",
            },
            "progress_note": {
                "loinc_code": "11506-3",
                "format_type": "free_text",
                "countries_supported": ["us", "jp"],
                "generation_frequency": "daily",
            },
            "discharge_summary": {
                "loinc_code": "18842-5",
                "format_type": "composition",
                "countries_supported": ["us", "jp"],
                "generation_frequency": "discharge_once",
            },
            "admission_nursing_assessment": {
                "loinc_code": "78390-2",
                "format_type": "composition",
                "countries_supported": ["us", "jp"],
                "generation_frequency": "admission_once",
            },
            "nursing_shift_note": {
                "loinc_code": "34746-8",
                "format_type": "free_text",
                "countries_supported": ["us", "jp"],
                "generation_frequency": "daily",
            },
            "nursing_discharge_summary": {
                "loinc_code": "34745-0",
                "format_type": "composition",
                "countries_supported": ["us", "jp"],
                "generation_frequency": "discharge_once",
            },
            "outpatient_soap": {
                "loinc_code": "34131-3",
                "format_type": "composition",
                "countries_supported": ["us", "jp"],
                "generation_frequency": "encounter_once",
            },
            "ed_note": {
                "loinc_code": "34878-9",
                "format_type": "composition",
                "countries_supported": ["us", "jp"],
                "generation_frequency": "encounter_once",
            },
            "ed_triage_note": {
                "loinc_code": "54094-8",
                "format_type": "free_text",
                "countries_supported": ["us", "jp"],
                "generation_frequency": "encounter_once",
            },
        }
    }
    with pytest.raises(ValueError, match="countries_supported empty"):
        reg_module._validate_document_type_specs(bad_data)


# === α-min-2 tests ===

def test_load_specs_returns_9_total() -> None:
    """3 α-min-1 + 6 α-min-2 = 9 total specs loaded from YAML."""
    load_document_type_specs.cache_clear()
    specs = load_document_type_specs()
    assert len(specs) == 9, f"Expected 9 specs (3 α-min-1 + 6 α-min-2), got {len(specs)}"


def test_supported_document_types_covers_9_entries() -> None:
    """SUPPORTED_DOCUMENT_TYPES frozenset has 9 members (α-min-1 3 + α-min-2 6)."""
    assert len(SUPPORTED_DOCUMENT_TYPES) == 9


def test_specs_for_encounter_type_outpatient_returns_only_outpatient_soap() -> None:
    """Among encounter-type-restricted specs, only OUTPATIENT_SOAP matches outpatient."""
    load_document_type_specs.cache_clear()
    outpatient_specs = specs_for_encounter_type("outpatient")
    # α-min-1 specs have empty encounter_types_supported (no restriction = also in results).
    # Among those WITH an explicit restriction, only outpatient_soap should match.
    restricted = [s for s in outpatient_specs if s.encounter_types_supported]
    keys = [s.type_key for s in restricted]
    assert keys == ["outpatient_soap"], f"Expected only outpatient_soap in restricted set, got {keys}"


def test_specs_for_encounter_type_inpatient_returns_6_specs() -> None:
    """3 α-min-1 (no restriction, matches all) + 3 nursing specs = 6 total for inpatient."""
    load_document_type_specs.cache_clear()
    inpatient_specs = specs_for_encounter_type("inpatient")
    assert len(inpatient_specs) == 6, f"Expected 6 inpatient specs, got {len(inpatient_specs)}"


def test_specs_for_encounter_type_emergency_returns_2_ed_specs() -> None:
    """ED_NOTE and ED_TRIAGE_NOTE are the only encounter-restricted specs for emergency."""
    load_document_type_specs.cache_clear()
    emergency_specs = specs_for_encounter_type("emergency")
    restricted = [s for s in emergency_specs if s.encounter_types_supported]
    keys = {s.type_key for s in restricted}
    assert keys == {"ed_note", "ed_triage_note"}, f"Expected ED specs only, got {keys}"


def test_encounter_once_generation_frequency_recognized() -> None:
    """encounter_once generation_frequency value loads without error and is stored correctly."""
    load_document_type_specs.cache_clear()
    specs = load_document_type_specs()
    assert specs[DocumentType.OUTPATIENT_SOAP].generation_frequency == "encounter_once"
    assert specs[DocumentType.ED_NOTE].generation_frequency == "encounter_once"
    assert specs[DocumentType.ED_TRIAGE_NOTE].generation_frequency == "encounter_once"


def test_daily_3shift_generation_frequency_recognized() -> None:
    """α-min-3: nursing_shift_note carries daily_3shift and loads without error."""
    load_document_type_specs.cache_clear()
    specs = load_document_type_specs()
    assert specs[DocumentType.NURSING_SHIFT_NOTE].generation_frequency == "daily_3shift"


def test_generation_frequencies_allowlist_contains_all_yaml_values() -> None:
    """Every YAML frequency value must be in the canonical allowlist (Layer 7 sanity)."""
    from clinosim.modules.document.narrative.registry import GENERATION_FREQUENCIES

    load_document_type_specs.cache_clear()
    for spec in load_document_type_specs().values():
        assert spec.generation_frequency in GENERATION_FREQUENCIES


def test_load_raises_on_unknown_generation_frequency() -> None:
    """α-min-3 Layer 7: an unknown generation_frequency raises fail-loud ValueError.

    Without this layer a typo like "daily3shift" would fall through the engine
    if/elif dispatch and silently emit zero documents (PR-90 class silent no-op).
    """
    import clinosim.modules.document.narrative.registry as reg_module

    ref_dir = Path(reg_module.__file__).resolve().parent.parent / "reference_data"
    with (ref_dir / "document_type_specs.yaml").open() as f:
        data = yaml.safe_load(f)
    data["specs"]["nursing_shift_note"]["generation_frequency"] = "daily3shift"
    with pytest.raises(ValueError, match="unknown generation_frequency"):
        reg_module._validate_document_type_specs(data)
