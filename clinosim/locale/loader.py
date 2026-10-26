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

import yaml

# Shared yaml-reading primitives — factored out so submodules under
# `clinosim/locale/loaders/` can import them without a cycle back
# through this module (hardcoded-review Phase B1).
from clinosim.locale._io import _COUNTRY_DIR_MAP, _LOCALE_DIR, _country_dir, _load_yaml

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
    "_validate_chronic_medications_route_vocabulary",
    "load_actuarial_life_table",
    "load_allergen_rxnorm_map",
    "load_chemo_regimens",
    "load_chief_complaint_translations",
    "load_chronic_followup",
    "load_chronic_medications",
    "load_comorbidity_progression_multipliers",
    "load_condition_mortality_smr",
    "load_department_display",
    "load_diet_type_display",
    "load_frequency_tokens",
    "load_health_screening_visit_reason",
    "load_inpatient_subjective_pool",
    "load_iv_infusion_defaults",
    "load_llm_prompt_labels",
    "load_med_terms",
    "load_med_terms_ja",
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
    "resolve_localized_display",
]


def _validate_demographics(data: dict) -> None:
    """Validate demographics.yaml at load time — fail loud on weight violations.

    Checks the OPTIONAL lifestyle_distribution block (smoking + alcohol per
    sex_key). The fallback ``_FALLBACK_DEMOGRAPHICS`` has no lifestyle block,
    so a missing block is a valid state (skip). When the block IS present,
    validate that each distribution has only non-negative weights with sum > 0 —
    these are the preconditions for
    ``normalize_probabilities(..., fallback="raise")`` at the
    ``population/engine.py`` callsites (smoking_dist :170, alcohol_dist :180).
    """
    if not isinstance(data, dict):
        raise ValueError(f"demographics.yaml: top-level must be a dict, got {type(data).__name__}")
    lifestyle = data.get("lifestyle_distribution")
    if lifestyle is None:
        return  # OK: optional block absent
    if not isinstance(lifestyle, dict):
        raise ValueError(f"demographics.yaml: lifestyle_distribution must be a dict, got {type(lifestyle).__name__}")
    for behavior in ("smoking", "alcohol"):
        per_sex = lifestyle.get(behavior)
        if per_sex is None:
            continue  # OK: behavior absent
        if not isinstance(per_sex, dict):
            raise ValueError(
                f"demographics.yaml: lifestyle_distribution.{behavior} must be a dict, got {type(per_sex).__name__}"
            )
        for sex_key, dist in per_sex.items():
            if not isinstance(dist, dict):
                raise ValueError(
                    f"demographics.yaml: lifestyle_distribution.{behavior}."
                    f"{sex_key!r} must be a dict, got {type(dist).__name__}"
                )
            weights: list[float] = []
            for level, w in dist.items():
                try:
                    w_f = float(w)
                except (TypeError, ValueError) as exc:
                    raise ValueError(
                        f"demographics.yaml: lifestyle_distribution.{behavior}."
                        f"{sex_key!r}.{level!r} weight non-numeric: {w!r}"
                    ) from exc
                if w_f < 0:
                    raise ValueError(
                        f"demographics.yaml: lifestyle_distribution.{behavior}."
                        f"{sex_key!r}.{level!r} has negative weight {w_f}"
                    )
                weights.append(w_f)
            if weights and sum(weights) <= 0:
                raise ValueError(
                    f"demographics.yaml: lifestyle_distribution.{behavior}.{sex_key!r} has zero-sum weights {weights}"
                )


def _validate_names(data: dict) -> None:
    """Validate names.yaml — surnames + given_names lists with non-negative weights.

    Tolerates the ``_FALLBACK_NAMES`` dict (which has small but valid weights).
    For each list present (``surnames`` / ``given_names_male`` /
    ``given_names_female``), requires each weight to be non-negative and the sum
    to be > 0 (precondition for ``normalize_probabilities(..., fallback="raise")``
    in population/engine.py callsites :485 and :517). An absent list is OK
    (validator does not require all three).
    """
    if not isinstance(data, dict):
        raise ValueError(f"names.yaml: top-level must be a dict, got {type(data).__name__}")
    for key in ("surnames", "given_names_male", "given_names_female"):
        items = data.get(key)
        if items is None:
            continue  # OK: optional list absent
        if not isinstance(items, list):
            raise ValueError(f"names.yaml: {key!r} must be a list, got {type(items).__name__}")
        if not items:
            continue  # OK: empty list (upstream normalize_probabilities raises on empty)
        weights: list[float] = []
        for entry in items:
            if not isinstance(entry, dict):
                raise ValueError(f"names.yaml: {key!r} entry must be a dict, got {entry!r}")
            try:
                w = float(entry.get("weight", 0))
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"names.yaml: {key!r}.{entry.get('name')!r} weight non-numeric: {entry.get('weight')!r}"
                ) from exc
            if w < 0:
                raise ValueError(f"names.yaml: {key!r}.{entry.get('name')!r} has negative weight {w}")
            weights.append(w)
        if weights and sum(weights) <= 0:
            raise ValueError(f"names.yaml: {key!r} has zero-sum weights")


def _validate_addresses(data: dict) -> None:
    """Validate addresses.yaml — cities list with non-negative weights.

    Tolerates missing / empty cities (upstream ``_generate_household_address``
    has a ``if not cities: return`` guard). When cities are present, requires
    non-negative weights with sum > 0 (precondition for
    ``normalize_probabilities(..., fallback="raise")`` at
    population/engine.py:664).
    """
    if not isinstance(data, dict):
        raise ValueError(f"addresses.yaml: top-level must be a dict, got {type(data).__name__}")
    cities = data.get("cities")
    if cities is None:
        return  # OK: empty fallback ({}) takes this path
    if not isinstance(cities, list):
        raise ValueError(f"addresses.yaml: 'cities' must be a list, got {type(cities).__name__}")
    if not cities:
        return  # OK: empty list (upstream guards against use)
    weights: list[float] = []
    for entry in cities:
        if not isinstance(entry, dict):
            raise ValueError(f"addresses.yaml: cities entry must be a dict, got {entry!r}")
        try:
            w = float(entry.get("weight", 1))
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"addresses.yaml: cities entry {entry.get('city')!r} weight non-numeric: {entry.get('weight')!r}"
            ) from exc
        if w < 0:
            raise ValueError(f"addresses.yaml: cities entry {entry.get('city')!r} has negative weight {w}")
        weights.append(w)
    if sum(weights) <= 0:
        raise ValueError("addresses.yaml: cities has zero-sum weights")


@lru_cache(maxsize=16)
def load_names(country: str) -> dict[str, Any]:
    """Load person name data for a country."""
    data = _load_yaml(_country_dir(country) / "names.yaml", fallback=_FALLBACK_NAMES)
    _validate_names(data)
    return data


@lru_cache(maxsize=16)
def load_naming_rules(country: str) -> dict[str, Any]:
    """Load naming rules for a country from shared/naming_rules.yaml."""
    all_rules = _load_yaml(_LOCALE_DIR / "shared" / "naming_rules.yaml", fallback={})
    dir_name = _COUNTRY_DIR_MAP.get(country, country.lower())
    return all_rules.get(dir_name, all_rules.get("us", {}))


@lru_cache(maxsize=32)
def load_terminology(domain: str, country: str) -> dict[str, str]:
    """Load display names for a domain (lab, diagnosis, drug, procedure).

    Example: load_terminology("lab", "JP") -> {"CRP": "C反応性蛋白", ...}
    """
    return _load_yaml(_country_dir(country) / f"terminology_{domain}.yaml", fallback={})


@lru_cache(maxsize=32)
def load_code_mapping(domain: str, country: str) -> dict[str, str]:
    """Load code mapping for a domain.

    Example: load_code_mapping("lab", "JP") -> {"CRP": "5C070", ...}

    META #1804 Phase 2.e (#1765 close): for ``domain == "drug"``, the
    returned mapping is now UNIONed with the Phase 1b drug-identity
    catalog (``clinosim/codes/data/drugs.yaml``). The legacy
    ``code_mapping_drug.yaml`` entries win on key collision for
    backwards compat; catalog entries fill the gap for drug names the
    legacy yaml never registered. Pre-Phase 2.e the US cohort emit path
    missed RxNorm coding on ~26 % of MedicationRequests because 78 of
    the catalog's 147 drug_ids had no matching legacy name entry.
    """
    legacy = _load_yaml(_country_dir(country) / f"code_mapping_{domain}.yaml", fallback={})
    if domain != "drug":
        return legacy
    # Union with catalog (legacy wins on conflict).
    code_field = "rxnorm" if country.lower() == "us" else "yj"
    merged: dict[str, str] = {}
    try:
        from clinosim.codes.drugs import all_drug_ids, resolve_drug

        drug_ids = all_drug_ids()
    except Exception:
        return legacy
    for drug_id in drug_ids:
        try:
            rec = resolve_drug(drug_id)
        except Exception:
            continue
        en = (rec.names.get("en") or "").strip()
        code = (rec.codes.get(code_field) or "").strip()
        if en and code and en not in legacy:
            merged[en] = code
    merged.update(legacy)
    return merged


@lru_cache(maxsize=8)
def load_formatting(country: str) -> dict[str, Any]:
    """Load formatting rules for a country (date, time, units)."""
    return _load_yaml(_country_dir(country) / "formatting.yaml", fallback=_FALLBACK_FORMATTING)


@lru_cache(maxsize=8)
def _load_demographics_cached(country: str) -> dict[str, Any]:
    """Internal cached loader for raw demographics YAML (no mutation)."""
    data = _load_yaml(_country_dir(country) / "demographics.yaml", fallback=_FALLBACK_DEMOGRAPHICS)
    _validate_demographics(data)
    return data


def load_demographics(country: str) -> dict[str, Any]:
    """Load demographic data for population generation.

    Injects ``_country`` into the returned dict so downstream consumers
    (e.g. activate_patient) can determine locale without an extra argument.
    The underlying YAML is cached; this function returns a fresh shallow copy
    each call so callers may safely mutate the top-level dict.
    """
    result = dict(_load_demographics_cached(country))
    result["_country"] = country
    return result


@lru_cache(maxsize=8)
def load_addresses(country: str) -> dict[str, Any]:
    """Load address/phone data for a country."""
    data = _load_yaml(_country_dir(country) / "addresses.yaml", fallback={})
    _validate_addresses(data)
    return data


# Cross-locale fallback defaults — authoritative yaml at
# `clinosim/locale/shared/fallback_defaults.yaml` (hardcoded-review
# Phase A14). The yaml carries all four fallback blocks
# (names / formatting / demographics / encounter_disposition); the
# Python aliases below preserve the historical module-level symbols so
# every call site stays unchanged. Loaded with a direct yaml.safe_load
# because `_load_yaml` is defined later in the file and these aliases
# evaluate at module-import time.
_FALLBACK_DEFAULTS_PATH = _LOCALE_DIR / "shared" / "fallback_defaults.yaml"


def _read_fallback_defaults() -> dict[str, Any]:
    if not _FALLBACK_DEFAULTS_PATH.exists():
        return {}
    with open(_FALLBACK_DEFAULTS_PATH, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    return raw if isinstance(raw, dict) else {}


_FALLBACK_DEFAULTS: dict[str, Any] = _read_fallback_defaults()

_FALLBACK_ENCOUNTER_DISPOSITION: dict[str, Any] = _FALLBACK_DEFAULTS.get("encounter_disposition", {}) or {}


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


# Fallback payloads for per-country yaml absence — same semantics as
# before (returned when `locale/<cc>/<name>.yaml` is missing). Authority
# yaml at `clinosim/locale/shared/fallback_defaults.yaml`
# (hardcoded-review Phase A14).
_FALLBACK_NAMES: dict[str, Any] = _FALLBACK_DEFAULTS.get("names", {}) or {}
_FALLBACK_FORMATTING: dict[str, Any] = _FALLBACK_DEFAULTS.get("formatting", {}) or {}
_FALLBACK_DEMOGRAPHICS: dict[str, Any] = _FALLBACK_DEFAULTS.get("demographics", {}) or {}
