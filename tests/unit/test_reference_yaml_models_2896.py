"""The reference YAMLs modelled in Issue #2896 load clean and reject unknown keys."""

from __future__ import annotations

import copy
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

from clinosim.datafiles import load_data_yaml
from clinosim.modules.document.narrative.registry import DocumentTypeSpecs, SectionCatalog
from clinosim.modules.document.reference_data_loaders import (
    CcPeConsistencyKeywords,
    ChronicMedClassHints,
    ChronicSoapTemplates,
    HedgingPhrases,
    HpiPertinentNegatives,
    JaOnlyFallbackSections,
    NarrativeExtrasWhitelists,
)
from clinosim.modules.hai import HaiAntibiogram
from clinosim.modules.hai.lab_lift import HaiLabLift
from clinosim.modules.imaging.engine import ImagingImpressionKeywords

pytestmark = pytest.mark.unit

_MODULES = Path(__file__).resolve().parents[2] / "clinosim" / "modules"


def _top(data: dict[str, Any]) -> dict[str, Any]:
    return data


def _first(data: dict[str, Any]) -> dict[str, Any]:
    return data[next(iter(data))]


def _first_spec(data: dict[str, Any]) -> dict[str, Any]:
    return _first(data["specs"])


def _first_class(data: dict[str, Any]) -> dict[str, Any]:
    return _first(data["classes"])


def _cc_keywords(data: dict[str, Any]) -> dict[str, Any]:
    return data["cc_keywords"]


_CASES: list[tuple[str, type[BaseModel], Callable[[dict[str, Any]], dict[str, Any]]]] = [
    ("document/reference_data/cc-pe-consistency-keywords.yaml", CcPeConsistencyKeywords, _cc_keywords),
    ("document/reference_data/chronic-med-class-hints.yaml", ChronicMedClassHints, _first_class),
    ("document/reference_data/chronic_soap_templates.yaml", ChronicSoapTemplates, _first),
    ("document/reference_data/document_type_specs.yaml", DocumentTypeSpecs, _first_spec),
    ("document/reference_data/hedging_phrases.yaml", HedgingPhrases, _first),
    ("document/reference_data/ja_only_fallback_sections.yaml", JaOnlyFallbackSections, _top),
    ("document/reference_data/narrative_extras_whitelists.yaml", NarrativeExtrasWhitelists, _top),
    ("document/reference_data/section_catalog.yaml", SectionCatalog, _first),
    ("hai/reference_data/hai_antibiogram.yaml", HaiAntibiogram, _top),
    ("hai/reference_data/hai_lab_lift.yaml", HaiLabLift, _top),
    ("imaging/reference_data/imaging-impression-keywords.yaml", ImagingImpressionKeywords, _top),
]


@pytest.mark.parametrize(("rel", "model", "_where"), _CASES)
def test_production_yaml_validates(rel: str, model: type[BaseModel], _where: Callable) -> None:
    model.model_validate(load_data_yaml(_MODULES / rel))


@pytest.mark.parametrize(("rel", "model", "where"), _CASES)
def test_unknown_key_is_rejected(rel: str, model: type[BaseModel], where: Callable) -> None:
    data = copy.deepcopy(load_data_yaml(_MODULES / rel))
    where(data)["misspelled_key"] = []
    with pytest.raises(ValidationError):
        model.model_validate(data)


def test_hpi_pertinent_negatives_rejects_a_non_list_entry() -> None:
    data = copy.deepcopy(load_data_yaml(_MODULES / "document/reference_data/hpi_pertinent_negatives.yaml"))
    HpiPertinentNegatives.model_validate(data)
    data[next(iter(data))] = {"misspelled_key": []}
    with pytest.raises(ValidationError):
        HpiPertinentNegatives.model_validate(data)
