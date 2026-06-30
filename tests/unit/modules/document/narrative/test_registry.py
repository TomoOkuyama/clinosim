"""DocumentTypeSpec registry tests."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from clinosim.modules.document.narrative.registry import (
    DocumentTypeSpec,
    load_document_type_specs,
    specs_for_country,
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
                "display_en": "H&P",
                "display_ja": "入院時記録",
                "format_type": "composition",
                # countries_supported intentionally missing
                "generation_frequency": "admission_once",
            },
            "progress_note": {
                "loinc_code": "11506-3",
                "display_en": "Progress note",
                "display_ja": "経過記録",
                "format_type": "free_text",
                "countries_supported": ["us", "jp"],
                "generation_frequency": "daily",
            },
            "discharge_summary": {
                "loinc_code": "18842-5",
                "display_en": "Discharge summary",
                "display_ja": "退院サマリ",
                "format_type": "composition",
                "countries_supported": ["us", "jp"],
                "generation_frequency": "discharge_once",
            },
        }
    }
    with pytest.raises(ValueError, match="missing countries_supported"):
        reg_module._validate_document_type_specs(bad_data)


def test_load_raises_on_empty_countries_supported() -> None:
    """6-layer validator fires on empty countries_supported list."""
    import clinosim.modules.document.narrative.registry as reg_module

    bad_data = {
        "specs": {
            "admission_hp": {
                "loinc_code": "34117-2",
                "display_en": "H&P",
                "display_ja": "入院時記録",
                "format_type": "composition",
                "countries_supported": [],  # empty
                "generation_frequency": "admission_once",
            },
            "progress_note": {
                "loinc_code": "11506-3",
                "display_en": "Progress note",
                "display_ja": "経過記録",
                "format_type": "free_text",
                "countries_supported": ["us", "jp"],
                "generation_frequency": "daily",
            },
            "discharge_summary": {
                "loinc_code": "18842-5",
                "display_en": "Discharge summary",
                "display_ja": "退院サマリ",
                "format_type": "composition",
                "countries_supported": ["us", "jp"],
                "generation_frequency": "discharge_once",
            },
        }
    }
    with pytest.raises(ValueError, match="countries_supported empty"):
        reg_module._validate_document_type_specs(bad_data)
