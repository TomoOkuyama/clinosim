"""DocumentTypeSpec registry (α-min-1 PR1).

Source = document_type_specs.yaml。countries_supported field で locale gating
(AD-55 PR3b-1 supplement pattern)。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from clinosim.types.document import DocumentType, FormatType

_HERE = Path(__file__).resolve().parent
_REF_DIR = _HERE.parent / "reference_data"


@dataclass(frozen=True)
class DocumentTypeSpec:
    """Document type registry entry."""

    type_key: str
    loinc_code: str
    display_en: str
    display_ja: str
    format_type: FormatType
    countries_supported: tuple[str, ...]
    generation_frequency: str
    composition_sections: tuple[str, ...] = field(default_factory=tuple)
    structured_form_yaml: str | None = None
    stage2_strategy: str = "template_only"
    llm_enabled_sections: tuple[str, ...] = field(default_factory=tuple)
    encounter_types_supported: tuple[str, ...] = field(default_factory=tuple)
    """Encounter types this spec applies to.

    Empty tuple (default) = no restriction; matches all encounter types (backwards-compat for
    α-min-1 specs like ADMISSION_HP / PROGRESS_NOTE / DISCHARGE_SUMMARY).
    Non-empty = explicit allowlist; values must be lowercase (e.g. 'inpatient', 'outpatient',
    'emergency'). Populated by Task 9 for the 6 new encounter-scoped document types.
    """


# α-min-2 scope = 9 doc types (α-min-1 3 + α-min-2 6)
SUPPORTED_DOCUMENT_TYPES: frozenset[DocumentType] = frozenset({
    # α-min-1
    DocumentType.ADMISSION_HP,
    DocumentType.PROGRESS_NOTE,
    DocumentType.DISCHARGE_SUMMARY,
    # α-min-2 additions
    DocumentType.ADMISSION_NURSING_ASSESSMENT,
    DocumentType.NURSING_SHIFT_NOTE,
    DocumentType.NURSING_DISCHARGE_SUMMARY,
    DocumentType.OUTPATIENT_SOAP,
    DocumentType.ED_NOTE,
    DocumentType.ED_TRIAGE_NOTE,
})


def _validate_document_type_specs(data: dict[str, Any]) -> None:
    """Fail-loud 6-layer validation of document_type_specs.yaml.

    Layer 1: empty top-level guard
    Layer 2: missing 'specs' key guard
    Layer 3: per-bucket (per-doc-type) empty guard
    Layer 4: forward + reverse coverage vs SUPPORTED_DOCUMENT_TYPES
    Layer 5: required-field check per entry
    Layer 6: countries_supported non-empty guard
    """
    if not data:
        raise ValueError("document_type_specs.yaml: empty top-level")
    specs = data.get("specs")
    if not specs:
        raise ValueError("document_type_specs.yaml: missing 'specs' key")
    yaml_keys = {DocumentType(k) for k in specs.keys()}
    if yaml_keys != SUPPORTED_DOCUMENT_TYPES:
        missing = SUPPORTED_DOCUMENT_TYPES - yaml_keys
        extra = yaml_keys - SUPPORTED_DOCUMENT_TYPES
        raise ValueError(
            f"document_type_specs.yaml ↔ SUPPORTED_DOCUMENT_TYPES drift: "
            f"missing={sorted(m.value for m in missing)}, "
            f"extra={sorted(e.value for e in extra)}"
        )
    required = (
        "loinc_code",
        "display_en",
        "display_ja",
        "format_type",
        "countries_supported",
        "generation_frequency",
    )
    for key, entry in specs.items():
        if not entry:
            raise ValueError(f"document_type_specs.yaml[{key}]: empty entry")
        for f in required:
            if f not in entry:
                raise ValueError(f"document_type_specs.yaml[{key}]: missing {f}")
        if not entry["countries_supported"]:
            raise ValueError(f"document_type_specs.yaml[{key}]: countries_supported empty")


@lru_cache(maxsize=1)
def load_document_type_specs() -> dict[DocumentType, DocumentTypeSpec]:
    """Load + validate document_type_specs.yaml. Cached singleton."""
    with (_REF_DIR / "document_type_specs.yaml").open() as f:
        data = yaml.safe_load(f)
    _validate_document_type_specs(data)
    result: dict[DocumentType, DocumentTypeSpec] = {}
    for key, entry in data["specs"].items():
        result[DocumentType(key)] = DocumentTypeSpec(
            type_key=key,
            loinc_code=entry["loinc_code"],
            display_en=entry["display_en"],
            display_ja=entry["display_ja"],
            format_type=FormatType(entry["format_type"]),
            countries_supported=tuple(entry["countries_supported"]),
            generation_frequency=entry["generation_frequency"],
            composition_sections=tuple(entry.get("composition_sections") or ()),
            structured_form_yaml=entry.get("structured_form_yaml"),
            stage2_strategy=entry.get("stage2_strategy", "template_only"),
            llm_enabled_sections=tuple(entry.get("llm_enabled_sections") or ()),
            encounter_types_supported=tuple(entry.get("encounter_types_supported") or ()),
        )
    return result


def specs_for_country(country: str) -> list[DocumentTypeSpec]:
    """Locale gating: return only specs supporting given country."""
    return [
        s for s in load_document_type_specs().values()
        if country.lower() in s.countries_supported
    ]


def specs_for_encounter_type(encounter_type: str) -> list[DocumentTypeSpec]:
    """Encounter-type gating: return only specs applicable to the given encounter_type.

    Semantics:
    - ``encounter_types_supported == ()`` (default) → no restriction; spec matches any encounter type.
      This is the backwards-compat path for α-min-1 specs (ADMISSION_HP / PROGRESS_NOTE /
      DISCHARGE_SUMMARY) which do not declare an explicit encounter-type scope.
    - Non-empty tuple → spec is restricted to the listed encounter types only.

    Matching is case-insensitive on the input: 'INPATIENT' and 'inpatient' both match a spec
    whose tuple contains 'inpatient'. YAML values are expected to be lowercase.

    Task 10 will intersect this result with ``specs_for_country`` to produce the final
    dispatch list for the document enricher.
    """
    encounter_type_lower = encounter_type.lower()
    return [
        s for s in load_document_type_specs().values()
        if not s.encounter_types_supported  # empty tuple = no restriction
        or encounter_type_lower in s.encounter_types_supported
    ]
