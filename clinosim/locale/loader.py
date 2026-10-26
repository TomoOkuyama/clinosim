"""Locale data loader — single access point for all country/language-specific data.

Holds only culture/country-dependent data. Terminology/display files were migrated
to clinosim/codes/ (international code systems); they no longer live under locale/.

Directory structure (country-based):
  locale/
    jp/
      names.yaml, addresses.yaml, demographics.yaml, formatting.yaml,
      identity.yaml, immunization_schedule.yaml, code_mapping_*.yaml
    us/
      (same shape as jp/)
    shared/
      naming_rules.yaml, chronic_medications.yaml, chronic_followup.yaml,
      narrative_*.yaml, chief_complaint_translations.yaml

Note: `drug_names_ja.yaml` was deleted under META #1849 Phase 5 Step 4
(2026-10-24). The drug-name EN→JA display mapping now lives in the
authority catalogs under `clinosim/codes/data/` (drugs.yaml +
clinosim-{imaging-exam-name,procedure-phrase,allergen-substance,
admin-form-display}.yaml); the free-text EN → JA display helper
`load_narrative_display_dict()` (renamed from `load_drug_names_ja` in
Phase 5 Step 3) UNIONs those catalogs into the dict shape callers
have always used.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

# Shared yaml-reading primitives — factored out so submodules under
# `clinosim/locale/loaders/` can import them without a cycle back
# through this module (hardcoded-review Phase B1).
from clinosim.locale._io import (
    _FALLBACK_ENCOUNTER_DISPOSITION,
    _LOCALE_DIR,
    _country_dir,
    _load_yaml,
)

# Narrative-renderer loader cluster — moved into
# `clinosim/locale/loaders/narrative.py` (hardcoded-review Phase B1).
# Re-exported at module scope so every historical
# `from clinosim.locale.loader import load_narrative_X` keeps working.
from clinosim.locale.loaders.clinical import (
    _iter_route_values,
    _validate_chronic_medications_route_vocabulary,
    load_actuarial_life_table,
    load_chemo_regimens,
    load_chronic_followup,
    load_chronic_medications,
    load_comorbidity_progression_multipliers,
    load_condition_mortality_smr,
    load_health_screening_visit_reason,
    load_iv_infusion_defaults,
    load_perinatal_config,
    load_pregnancy_substitutions,
    load_reference_ranges,
    load_single_gene_diseases,
    load_specialty_routing,
)
from clinosim.locale.loaders.demographics import (
    _load_demographics_cached,
    _validate_addresses,
    _validate_demographics,
    _validate_names,
    load_addresses,
    load_code_mapping,
    load_demographics,
    load_formatting,
    load_names,
    load_naming_rules,
    load_terminology,
)
from clinosim.locale.loaders.medical_display import (
    load_allergen_rxnorm_map,
    load_department_display,
    load_diet_type_display,
    load_frequency_tokens,
    load_med_terms,
    load_med_terms_ja,
    load_occupation_display,
    load_prefecture_jis_x_0401_map,
)
from clinosim.locale.loaders.narrative import (
    _load_country_language_map,
    load_chief_complaint_translations,
    load_inpatient_subjective_pool,
    load_llm_prompt_labels,
    load_narrative_archetypes,
    load_narrative_complications,
    load_narrative_display_dict,
    load_narrative_imaging,
    load_narrative_lab_flags,
    load_narrative_lab_names,
    load_narrative_labels,
    load_narrative_op_approach,
    load_narrative_op_implants,
    load_narrative_stage_tokens,
    resolve_localized_display,
)

__all__ = [
    "_country_dir",
    "_iter_route_values",
    "_load_country_language_map",
    "_load_demographics_cached",
    "_validate_addresses",
    "_validate_chronic_medications_route_vocabulary",
    "_validate_demographics",
    "_validate_names",
    "load_actuarial_life_table",
    "load_addresses",
    "load_allergen_rxnorm_map",
    "load_chemo_regimens",
    "load_chief_complaint_translations",
    "load_chronic_followup",
    "load_chronic_medications",
    "load_code_mapping",
    "load_comorbidity_progression_multipliers",
    "load_condition_mortality_smr",
    "load_demographics",
    "load_department_display",
    "load_diet_type_display",
    "load_formatting",
    "load_frequency_tokens",
    "load_health_screening_visit_reason",
    "load_inpatient_subjective_pool",
    "load_iv_infusion_defaults",
    "load_llm_prompt_labels",
    "load_med_terms",
    "load_med_terms_ja",
    "load_names",
    "load_naming_rules",
    "load_narrative_archetypes",
    "load_narrative_complications",
    "load_narrative_display_dict",
    "load_narrative_imaging",
    "load_narrative_lab_flags",
    "load_narrative_lab_names",
    "load_narrative_labels",
    "load_narrative_op_approach",
    "load_narrative_op_implants",
    "load_narrative_stage_tokens",
    "load_occupation_display",
    "load_perinatal_config",
    "load_prefecture_jis_x_0401_map",
    "load_pregnancy_substitutions",
    "load_reference_ranges",
    "load_single_gene_diseases",
    "load_specialty_routing",
    "load_terminology",
    "resolve_localized_display",
]


@lru_cache(maxsize=1)
def load_encounter_disposition_defaults() -> dict[str, Any]:
    """Load Encounter.hospitalization fallback defaults (Issue #941).

    Single-source-of-truth for the HL7 admit-source / discharge-disposition
    fallback codes and JP-CLINS ValueSet binding URLs used by the FHIR emit
    path when the CIF encounter carries no explicit disposition. See
    ``clinosim/locale/shared/encounter_disposition_defaults.yaml``.
    """
    raw = _load_yaml(
        _LOCALE_DIR / "shared" / "encounter_disposition_defaults.yaml",
        fallback=_FALLBACK_ENCOUNTER_DISPOSITION,
    )
    if not isinstance(raw, dict):
        return _FALLBACK_ENCOUNTER_DISPOSITION
    # Fail-soft merge with fallback so a partial yaml still yields a
    # complete config (each required key has a hardcoded default).
    merged: dict[str, Any] = {}
    for slot, defaults in _FALLBACK_ENCOUNTER_DISPOSITION.items():
        entry = raw.get(slot) or {}
        if not isinstance(entry, dict):
            entry = {}
        merged[slot] = {**defaults, **entry}
    return merged


# ---------------------------------------------------------------------------
# Narrative-renderer vocabulary loaders — moved to
# ``clinosim/locale/loaders/narrative.py`` (hardcoded-review Phase B1).
# Re-exported at module scope at the top of this file so every
# ``from clinosim.locale.loader import load_narrative_X`` import keeps
# working.
# ---------------------------------------------------------------------------


@lru_cache(maxsize=2)
def load_ambulatory_visit_length(country: str) -> dict[str, Any]:
    """Load per-visit-type ambulatory (outpatient) encounter length distributions.

    Returned shape:

        {
          "visit_types": {
             "chronic_followup": {"min": int, "mode": int, "max": int},
             "post_discharge":   {"min": int, "mode": int, "max": int},
             "pediatric_visit":  {"min": int, "mode": int, "max": int},
             "health_screening": {"min": int, "mode": int, "max": int},
             ...
          },
          "default": {"min": int, "mode": int, "max": int},
        }

    Issue #927: pre-fix outpatient length was a flat ``rng.integers(15, 45)``
    regardless of visit purpose, which excluded the 5-10 min return-visit
    peak that dominates JP primary-care volume. This loader is the single
    source-of-truth for the per-visit-type triangular distributions used
    by ``clinosim.simulator.outpatient._sample_ambulatory_visit_length_minutes``.
    """
    fallback = {
        "visit_types": {},
        "default": {"min": 15, "mode": 25, "max": 45},
    }
    data = _load_yaml(_country_dir(country) / "ambulatory_visit_length.yaml", fallback=fallback)
    _validate_ambulatory_visit_length(data, country)
    return data


def _validate_ambulatory_visit_length(data: dict, country: str) -> None:
    """Fail loud if the yaml is malformed — every distribution must satisfy
    0 < min <= mode <= max. Triangular sampling silently degenerates when
    the invariant is violated, so we catch it at import time."""
    if not isinstance(data, dict):
        raise ValueError(
            f"ambulatory_visit_length.yaml ({country}): top-level must be a dict, got {type(data).__name__}"
        )

    def _check_bucket(name: str, bucket: Any) -> None:
        if not isinstance(bucket, dict):
            raise ValueError(
                f"ambulatory_visit_length.yaml ({country}): {name!r} must be a dict, got {type(bucket).__name__}"
            )
        for k in ("min", "mode", "max"):
            if k not in bucket:
                raise ValueError(f"ambulatory_visit_length.yaml ({country}): {name!r} missing key {k!r}")
            v = bucket[k]
            if not isinstance(v, int | float) or isinstance(v, bool):
                raise ValueError(f"ambulatory_visit_length.yaml ({country}): {name}.{k}={v!r} must be numeric")
        lo, mode, hi = float(bucket["min"]), float(bucket["mode"]), float(bucket["max"])
        if not (0 < lo <= mode <= hi):
            raise ValueError(
                f"ambulatory_visit_length.yaml ({country}): {name!r} requires 0 < min ({lo}) <= "
                f"mode ({mode}) <= max ({hi})"
            )

    default = data.get("default")
    if default is None:
        raise ValueError(f"ambulatory_visit_length.yaml ({country}): missing top-level 'default' block")
    _check_bucket("default", default)

    visit_types = data.get("visit_types", {}) or {}
    if not isinstance(visit_types, dict):
        raise ValueError(
            f"ambulatory_visit_length.yaml ({country}): 'visit_types' must be a dict, got {type(visit_types).__name__}"
        )
    for name, bucket in visit_types.items():
        _check_bucket(f"visit_types.{name}", bucket)


@lru_cache(maxsize=8)
def load_external_organizations(country: str) -> list[dict[str, Any]]:
    """Load the external referring / receiving hospital catalog for a country.

    Issue #924: JP-CLINS 診療情報提供書 (referral letter, LOINC 57133-1)
    Composition emit needs a pool of external Organizations to reference in
    the 910 (紹介先) section — previously both 920 and 910 collapsed to
    ``Organization/hospital-main`` for every referral. Returns the flat
    ``external_hospitals`` list from ``<country>/external_organizations.yaml``
    (list of dicts with ``id``, ``name``, ``type``, ``type_code``,
    ``type_display``, ``address``, ``institution_code``, ``phone``).

    Countries without the file (US today) get an empty list — callers must
    treat that as "no external-organization catalog available" and fall back
    to their prior emit behavior.
    """
    data = _load_yaml(_country_dir(country) / "external_organizations.yaml", fallback={})
    entries = data.get("external_hospitals", []) if isinstance(data, dict) else []
    return list(entries) if isinstance(entries, list) else []


@lru_cache(maxsize=8)
def load_practitioner_qualifications(country: str) -> dict[str, Any]:
    """Load JP MHLW national-license qualification + license-number tables
    (Issue #962).

    Returned shape:

        {
          "code_system": "urn:oid:...",
          "license_identifier_salt": "practitioner-license-2026",
          "qualification_codes": {
             "physician": {"code": "MedicalDoctor", "display": "医師"},
             ...
          },
          "physician_specialty_boards": {
             "cardiology": {"code": "CardiologySpecialist",
                            "display": "循環器専門医"},
             ...
          },
          "license_identifiers": {
             "physician": {"system": "http://...",
                            "label": "医籍番号", "prefix": "第",
                            "suffix": "号", "digits": 6},
             ...
          },
        }

    Empty dict if the file is absent (US, `_template`) — callers then skip
    the JP-CLINS qualification / license identifier emit and fall back to
    the existing v2-0360 / text-only qualification path.
    """
    return _load_yaml(_country_dir(country) / "practitioner_qualifications.yaml", fallback={})


@lru_cache(maxsize=8)
def load_identity_config(country: str) -> dict[str, Any]:
    """Load resident identifier / insurance numbering config for a country (AD-54).

    Returns payer representative sets, age-banded card/insurance rates, household
    correlation, and insurance category distribution. Empty dict if absent (e.g. US,
    which keeps its existing insurance handling in Phase 1).
    """
    return _load_yaml(_country_dir(country) / "identity.yaml", fallback={})


# _load_yaml moved to clinosim/locale/_io.py (hardcoded-review Phase B1)
# and imported at the top of this module.
