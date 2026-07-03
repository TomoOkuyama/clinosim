"""DocumentTypeSpec registry (α-min-1 PR1).

Source = document_type_specs.yaml。countries_supported field で locale gating
(AD-55 PR3b-1 supplement pattern)。
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

# DocumentTypeSpec moved to clinosim/types/document.py (N-chain, types rule);
# re-exported here so all historical imports keep working.
from clinosim.types.document import DocumentType, DocumentTypeSpec, FormatType

__all__ = [
    "DocumentTypeSpec",
    "GENERATION_FREQUENCIES",
    "STAGE2_STRATEGIES",
    "SUPPORTED_DOCUMENT_TYPES",
    "load_document_type_specs",
    "specs_for_country",
    "specs_for_encounter_type",
]

_HERE = Path(__file__).resolve().parent
_REF_DIR = _HERE.parent / "reference_data"


# α-min-3: canonical allowlist of generation_frequency values. The engine
# dispatch (engine.py document_enricher) is an if/elif chain — an unknown
# frequency value would fall through and silently emit ZERO documents for
# that spec (PR-90 class silent no-op). Fail-loud here at YAML load time so
# a typo (e.g. "daily3shift") raises before any simulation runs. Adding a
# new frequency requires BOTH the engine branch and this allowlist entry.
GENERATION_FREQUENCIES: frozenset[str] = frozenset({
    "admission_once",
    "daily",
    "daily_3shift",  # α-min-3: 3 nursing notes per LOS day (night/day/evening)
    "discharge_once",
    "encounter_once",
})

# N-chain adv-1 I-1: canonical allowlist of stage2_strategy values. The
# replacement-strategy dispatch (replacement_strategy.apply_replacement_strategy)
# treats an unknown value as "return template output" — a typo like
# "template-seed" would silently no-op the ENTIRE LLM path (PR-90 class).
# Fail-loud here at YAML load time. Adding a new strategy requires BOTH the
# dispatch branch and this allowlist entry.
STAGE2_STRATEGIES: frozenset[str] = frozenset({
    "template_only",
    "template_seed",
})

# α-min-2 scope = 9 doc types (α-min-1 3 + α-min-2 6); chain 2 adds 1 = 10
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
    # chain 2 addition
    DocumentType.ADMISSION_CARE_PLAN,
})


def _validate_document_type_specs(data: dict[str, Any]) -> None:
    """Fail-loud 9-layer validation of document_type_specs.yaml.

    Layer 1: empty top-level guard
    Layer 2: missing 'specs' key guard
    Layer 3: per-bucket (per-doc-type) empty guard
    Layer 4: forward + reverse coverage vs SUPPORTED_DOCUMENT_TYPES
    Layer 5: required-field check per entry
    Layer 6: countries_supported non-empty guard
    Layer 7: generation_frequency ∈ GENERATION_FREQUENCIES allowlist (α-min-3;
             unknown value would silently no-op in the engine dispatch)
    Layer 8: stage2_strategy ∈ STAGE2_STRATEGIES allowlist (N-chain adv-1 I-1;
             the replacement-strategy dispatch returns template output on an
             unknown value → typo = silent no-op of the whole LLM path)
    Layer 9: template_seed coherence (N-chain adv-1 I-1) — requires non-empty
             llm_enabled_sections, composition format (free_text /
             questionnaire_response renderers emit no sections to seed from),
             and llm_enabled_sections ⊆ composition_sections (an undeclared
             section would be fabricated from an empty seed — hallucination
             risk)
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
        if entry["generation_frequency"] not in GENERATION_FREQUENCIES:
            raise ValueError(
                f"document_type_specs.yaml[{key}]: unknown generation_frequency "
                f"{entry['generation_frequency']!r} — engine dispatch would silently "
                f"emit no documents. Allowed: {sorted(GENERATION_FREQUENCIES)}"
            )
        # Layer 8: stage2_strategy allowlist
        strategy = entry.get("stage2_strategy", "template_only")
        if strategy not in STAGE2_STRATEGIES:
            raise ValueError(
                f"document_type_specs.yaml[{key}]: unknown stage2_strategy "
                f"{strategy!r} — replacement-strategy dispatch would silently "
                f"return template output (LLM path no-op). "
                f"Allowed: {sorted(STAGE2_STRATEGIES)}"
            )
        # Layer 9: template_seed coherence
        if strategy == "template_seed":
            llm_sections = tuple(entry.get("llm_enabled_sections") or ())
            if not llm_sections:
                raise ValueError(
                    f"document_type_specs.yaml[{key}]: stage2_strategy=template_seed "
                    f"requires a non-empty llm_enabled_sections list (empty list = "
                    f"dead LLM wiring)"
                )
            if entry["format_type"] != "composition":
                raise ValueError(
                    f"document_type_specs.yaml[{key}]: stage2_strategy=template_seed "
                    f"requires format_type=composition — "
                    f"{entry['format_type']!r} renderers emit no sections, so "
                    f"per-section seed replacement has nothing to seed from"
                )
            declared = set(entry.get("composition_sections") or ())
            unknown = set(llm_sections) - declared
            if unknown:
                raise ValueError(
                    f"document_type_specs.yaml[{key}]: llm_enabled_sections "
                    f"{sorted(unknown)} not declared in composition_sections — "
                    f"an undeclared section would be LLM-fabricated from an "
                    f"empty seed (hallucination risk)"
                )


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
