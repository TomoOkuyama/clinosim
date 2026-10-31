"""Demographics / names / addresses / formatting / terminology /
code-mapping locale loaders, plus the trio of yaml validators that
guard those files.

Extracted from the historical god-file ``clinosim/locale/loader.py`` as
step C2c of the full-review Phase C locale split, continuing B1 /
C2a (clinical) / C2b (medical display).

The three ``_validate_*`` helpers are kept with the loaders they guard
(same source of truth: a validator and its yaml belong together).
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from clinosim.locale._io import (
    _COUNTRY_DIR_MAP,
    _FALLBACK_DEMOGRAPHICS,
    _FALLBACK_FORMATTING,
    _FALLBACK_NAMES,
    _LOCALE_DIR,
    _country_dir,
    _load_yaml,
)


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


def drug_code(drug_ref: str, country: str) -> tuple[str, str] | None:
    """``(system_key, code)`` emitted for a drug (catalog id, English name or
    alias) in ``country``: the drug code mapping, which unions the catalog with
    the legacy ``code_mapping_drug.yaml``; ``None`` when the drug has no code
    there (Issue #2262)."""
    from clinosim.codes.drugs import drug_system_key, find_drug

    rec = find_drug(drug_ref)
    name = rec.names.get("en", "") if rec else drug_ref
    code = load_code_mapping("drug", country).get(name, "")
    return (drug_system_key(code, country), code) if code else None


def lab_code(lab_name: str, country: str) -> tuple[str, str] | None:
    """``(system_key, code)`` of a lab result for ``country``: LOINC for the
    US, JLAC10 for JP, from ``code_mapping_lab.yaml``; ``None`` when the
    analyte is unmapped (Issue #2261)."""
    from clinosim.codes import system_key_for

    code = load_code_mapping("lab", country).get(lab_name, "")
    return (system_key_for("lab", country), code) if code else None


def lab_codes(lab_name: str) -> tuple[str, ...]:
    """Every code a lab result carries across the supported locales (US LOINC,
    JP JLAC10), read from ``code_mapping_lab.yaml`` (Issue #2301).

    For checks that read a mixed or unknown-locale cohort and must recognise an
    analyte by code without restating the codes.
    """
    codes = (load_code_mapping("lab", country).get(lab_name, "") for country in ("US", "JP"))
    return tuple(dict.fromkeys(c for c in codes if c))


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
