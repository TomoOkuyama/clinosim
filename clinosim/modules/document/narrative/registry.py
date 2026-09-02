"""DocumentTypeSpec registry (α-min-1 PR1).

Source = document_type_specs.yaml. The ``countries_supported`` field on
each entry drives locale gating (AD-55 PR3b-1 supplement pattern).
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
    "SectionCatalogEntry",
    "load_section_catalog",
    "resolve_section_title",
    "resolve_section_loinc",
]

_HERE = Path(__file__).resolve().parent
_REF_DIR = _HERE.parent / "reference_data"


# α-min-3: canonical allowlist of generation_frequency values. The engine
# dispatch (engine.py document_enricher) is an if/elif chain — an unknown
# frequency value would fall through and silently emit ZERO documents for
# that spec (PR-90 class silent-no-op). Fail-loud here at YAML load time so
# a typo (e.g. "daily3shift") raises before any simulation runs. Adding a
# new frequency requires BOTH the engine branch and this allowlist entry.
GENERATION_FREQUENCIES: frozenset[str] = frozenset(
    {
        "admission_once",
        "admission_once_los_gt_7",  # chain 2: nutrition_care_plan (MHLW LOS>7 mandate)
        "admission_once_if_rehab_sessions",  # chain 2: rehabilitation_plan (RehabSession presence gate)
        "daily",
        "daily_3shift",  # α-min-3: 3 nursing notes per LOS day (night/day/evening)
        "discharge_once",
        "discharge_once_if_alive",  # Issue #961 ext: generic 退院時サマリー — skips deceased encounters (DDS replaces)
        "discharge_fraction_20pct",  # P2-13 PR2b: JP-CLINS referral_note (20% of discharges)
        "discharge_once_if_deceased",  # Issue #961: 死亡診断書 (deceased-inpatient-only)
        "discharge_once_if_deceased_replaces",  # Issue #961 ext: 死亡退院サマリー (replaces generic DS)
        "encounter_once",
        "checkup_once",  # P2-13 PR3: JP-eCheckup health_checkup_report (opt-in module)
        # Issue #991: operative_note fires once per encounter that has a
        # surgical ProcedureRecord (category_code == "387713003"). Engine
        # picks the earliest surgical procedure by start_datetime, stamps
        # `related_procedure_id`, and authored_datetime = that procedure's
        # end_datetime (op note written immediately after the operation).
        "per_surgical_encounter",
        "per_bedside_procedure",  # Issue #992: procedure_note (one Composition per bedside Procedure)
    }
)

# N-chain adv-1 I-1: canonical allowlist of stage2_strategy values. The
# replacement-strategy dispatch (replacement_strategy.apply_replacement_strategy)
# treats an unknown value as "return template output" — a typo like
# "template-seed" would silently no-op the ENTIRE LLM path (PR-90 class).
# Fail-loud here at YAML load time. Adding a new strategy requires BOTH the
# dispatch branch and this allowlist entry.
STAGE2_STRATEGIES: frozenset[str] = frozenset(
    {
        "template_only",
        "template_seed",
        # Session 88j Tier 1 uplift: bundle every `llm_enabled_sections`
        # entry into ONE LLM call per document so cache keys are still
        # bucket-level (disease/day/severity) but request count drops from
        # per-section to per-document, and generated sections share one
        # narrative voice (internal S↔A↔P consistency preserved).
        "template_seed_bundle",
    }
)

# α-min-2 scope = 9 doc types (α-min-1 3 + α-min-2 6); chain 2 adds 3 = 12
SUPPORTED_DOCUMENT_TYPES: frozenset[DocumentType] = frozenset(
    {
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
        # chain 2 additions
        DocumentType.ADMISSION_CARE_PLAN,
        DocumentType.NUTRITION_CARE_PLAN,
        DocumentType.REHABILITATION_PLAN,
        # P2-13 PR2b: JP-CLINS 診療情報提供書 (referral letter)
        DocumentType.REFERRAL_NOTE,
        # P2-13 PR3: JP-eCheckup 健診結果報告書 (health checkup report, opt-in)
        DocumentType.HEALTH_CHECKUP_REPORT,
        # Issue #961: 死亡診断書 (death certificate) — 医師法第 20 条 mandate
        DocumentType.DEATH_CERTIFICATE,
        # Issue #961 extension: 死亡退院サマリー (death discharge summary) —
        # replaces the generic 退院時サマリー on deceased-inpatient encounters.
        DocumentType.DEATH_DISCHARGE_SUMMARY,
        # Issue #991: 手術記録 (operative note) — LOINC 11504-8.
        # Fires per surgical encounter (category_code == "387713003").
        DocumentType.OPERATIVE_NOTE,
        # Issue #992: 処置記録 (procedure note) — one Composition per
        # bedside Procedure (endoscopy / CV line / LP / thoracentesis / etc.).
        DocumentType.PROCEDURE_NOTE,
    }
)


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
             unknown value → typo = silent-no-op of the whole LLM path)
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
        # Layer 9: template_seed / template_seed_bundle coherence
        if strategy in ("template_seed", "template_seed_bundle"):
            llm_sections = tuple(entry.get("llm_enabled_sections") or ())
            if not llm_sections:
                raise ValueError(
                    f"document_type_specs.yaml[{key}]: stage2_strategy=template_seed "
                    f"requires a non-empty llm_enabled_sections list (empty list = "
                    f"dead LLM wiring)"
                )
            # template_seed operates on the per-section seed produced by the
            # template. Composition documents produce this naturally. Free-
            # text documents (e.g. progress_note) may also participate when
            # their template renderer populates `sections` alongside `raw_text`
            # AND declares `composition_sections` here so `llm_enabled_sections`
            # can be validated against a known set (session-88j Tier 1 uplift).
            # The FREE_TEXT `_apply_template_seed_strategy` post-hook rebuilds
            # `raw_text` from the possibly-replaced sections via the
            # renderer-set `raw_text_rejoin` metadata.
            format_type = entry["format_type"]
            if format_type not in ("composition", "free_text"):
                raise ValueError(
                    f"document_type_specs.yaml[{key}]: stage2_strategy=template_seed "
                    f"requires format_type in (composition, free_text) — "
                    f"{format_type!r} renderers emit no sections, so per-section "
                    f"seed replacement has nothing to seed from"
                )
            declared = set(entry.get("composition_sections") or ())
            if not declared:
                raise ValueError(
                    f"document_type_specs.yaml[{key}]: stage2_strategy=template_seed "
                    f"requires composition_sections to declare the seed slot names — "
                    f"llm_enabled_sections cannot be validated against an empty set"
                )
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
            composition_sections_jp=tuple(entry.get("composition_sections_jp") or ()),
            llm_enabled_sections_jp=tuple(entry.get("llm_enabled_sections_jp") or ()),
        )
    return result


def specs_for_country(country: str) -> list[DocumentTypeSpec]:
    """Locale gating: return only specs supporting given country."""
    return [s for s in load_document_type_specs().values() if country.lower() in s.countries_supported]


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
        s
        for s in load_document_type_specs().values()
        if not s.encounter_types_supported  # empty tuple = no restriction
        or encounter_type_lower in s.encounter_types_supported
    ]


# =============================================================================
# Section catalog (META #957 close-out session 97, 2026-09-02)
# =============================================================================
#
# Single source of truth for section slug metadata (title_ja / title_en /
# loinc). Before this catalog existed, the same information was authored
# across three parallel dicts in
# `clinosim/modules/output/fhir_r4/documents/composition.py` — asymmetric
# updates produced silent drift (PR #991 OPERATIVE_NOTE landing forgot the
# JA-side dict; the raw slug `op_procedure_name` leaked as
# `Composition.section.title`; patched separately by PR #1055).
#
# Load-time validation (`_validate_section_catalog`) enforces:
#   1. Every slug has non-empty title_ja / title_en / loinc.
#   2. Every slug listed in `document_type_specs.yaml::composition_sections*`
#      is registered in the catalog (missing → ImportError, no silent drift).
#
# The FHIR emit layer (`_localize_section_title` / `_loinc_for_section`)
# reads via `resolve_section_title` / `resolve_section_loinc` — the emit
# layer holds no locale mapping of its own after PR that lands this catalog.


class SectionCatalogEntry:
    """One row of the section catalog. Fields align with the yaml schema."""

    __slots__ = ("slug", "title_ja", "title_en", "loinc", "description")

    def __init__(self, slug: str, title_ja: str, title_en: str, loinc: str, description: str = "") -> None:
        self.slug = slug
        self.title_ja = title_ja
        self.title_en = title_en
        self.loinc = loinc
        self.description = description

    def title_for(self, lang: str) -> str:
        """Return the localized title for a Composition emit language.

        `lang` is a two-letter locale code (`"ja"` for JP, anything else
        falls back to EN — matches the existing `_localize_section_title`
        contract).
        """
        return self.title_ja if str(lang).lower() == "ja" else self.title_en

    def __repr__(self) -> str:
        return f"SectionCatalogEntry(slug={self.slug!r}, loinc={self.loinc!r})"


def _validate_section_catalog(catalog: dict[str, dict[str, Any]]) -> None:
    """Fail-loud validation of the section_catalog.yaml payload.

    Runs at import time (via `load_section_catalog`). Fails on:
      * A slug entry missing any of title_ja / title_en / loinc.
      * Any slug authored in `document_type_specs.yaml::composition_sections*`
        that is not registered in the catalog. This is the drift class the
        catalog exists to prevent — a new section type added to the doc-spec
        yaml without a catalog entry would previously silent-fall-through
        to a raw machine slug title.
    """
    incomplete: list[str] = []
    for slug, entry in catalog.items():
        if not isinstance(entry, dict):
            incomplete.append(f"{slug} (not a dict)")
            continue
        for field in ("title_ja", "title_en", "loinc"):
            if not entry.get(field):
                incomplete.append(f"{slug}.{field}")
    if incomplete:
        raise ValueError(
            f"section_catalog.yaml: incomplete entries — {incomplete[:20]}"
            + (f" (and {len(incomplete) - 20} more)" if len(incomplete) > 20 else "")
        )

    # Cross-reference: every slug in document_type_specs.yaml must appear
    # in the catalog. Detects the drift class where a new doc type lands
    # with composition_sections referencing a slug that has no localization.
    specs = load_document_type_specs()
    doc_spec_slugs: set[str] = set()
    for spec in specs.values():
        doc_spec_slugs.update(spec.composition_sections or ())
        doc_spec_slugs.update(getattr(spec, "composition_sections_jp", None) or ())
    missing = sorted(doc_spec_slugs - set(catalog.keys()))
    if missing:
        raise ValueError(
            f"section_catalog.yaml: {len(missing)} slug(s) authored in "
            f"document_type_specs.yaml are missing from the catalog — {missing[:20]}"
            + (f" (and {len(missing) - 20} more)" if len(missing) > 20 else "")
            + ". Add an entry with title_ja / title_en / loinc, or remove "
            "the slug from document_type_specs.yaml."
        )


@lru_cache(maxsize=1)
def load_section_catalog() -> dict[str, SectionCatalogEntry]:
    """Load + validate `section_catalog.yaml`. Cached singleton."""
    with (_REF_DIR / "section_catalog.yaml").open() as f:
        data = yaml.safe_load(f) or {}
    _validate_section_catalog(data)
    out: dict[str, SectionCatalogEntry] = {}
    for slug, entry in data.items():
        out[slug] = SectionCatalogEntry(
            slug=slug,
            title_ja=entry["title_ja"],
            title_en=entry["title_en"],
            loinc=entry["loinc"],
            description=entry.get("description", ""),
        )
    return out


def resolve_section_title(slug: str, lang: str) -> str:
    """Return the localized `Composition.section.title` for `slug`.

    Called from the FHIR emit layer (`composition.py::_localize_section_title`
    is now a thin wrapper around this). Returns the empty string when the
    slug is unknown — callers may fall back to the raw slug for backward
    compatibility, but production code paths should never see an unknown
    slug because `_validate_section_catalog` enforces coverage at load time.
    """
    entry = load_section_catalog().get(slug)
    return entry.title_for(lang) if entry is not None else ""


def resolve_section_loinc(slug: str) -> str:
    """Return the LOINC code for `slug`, or the empty string if unknown."""
    entry = load_section_catalog().get(slug)
    return entry.loinc if entry is not None else ""
