"""Country profile — the data that selects a country's behaviour (Issue #3140).

``docs/design-guides/country-profile-spec.md`` §3-§4. A country's profile is
``clinosim/locale/<cc>/country.yaml`` deep-merged over
``clinosim/locale/_root/country.yaml`` and validated by :class:`CountryProfile`
(unknown keys rejected; every code system, FHIR profile, feature and
implementation name checked). :func:`country_profile` returns the cached
profile and raises on an unknown country — it never falls back to the US.

Named implementations: an algorithm a country selects by name registers with
:func:`register_implementation`; :func:`implementation` returns the one the
country's profile names. Registration happens when the modules in
:data:`IMPLEMENTATION_MODULES` are imported (explicit, no discovery); a profile
naming an unregistered implementation fails when it is loaded.
"""

from __future__ import annotations

import copy
import importlib
from collections.abc import Callable
from functools import cache, lru_cache
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from clinosim.datafiles import load_data_yaml

__all__ = [
    "CODE_SYSTEM_KINDS",
    "FHIR_PROFILES",
    "IMPLEMENTATION_MODULES",
    "CountryProfile",
    "country_profile",
    "deep_merge",
    "implementation",
    "load_profile_data",
    "register_implementation",
    "supported_countries",
    "validate_implementations",
]

_LOCALE = Path(__file__).resolve().parent / "locale"
_ROOT = _LOCALE / "_root" / "country.yaml"
_PROFILE_FILE = "country.yaml"

CODE_SYSTEM_KINDS: tuple[str, ...] = ("lab", "diagnosis", "drug", "procedure", "microbiology")
FHIR_PROFILES: frozenset[str] = frozenset({"us_core", "jp_core", "jp_clins", "jp_echeckup"})

# Modules that register named implementations at import (spec §4). Imported
# before a profile's implementation names are checked.
IMPLEMENTATION_MODULES: tuple[str, ...] = (
    "clinosim.modules.physiology.egfr",
    "clinosim.modules.identity.providers.us",
    "clinosim.modules.identity.providers.jp",
    "clinosim.modules.triage.engine",
    "clinosim.modules.output.fhir_r4.labs.coding_strategy",
    "clinosim.codes.drugs",
)


class _Formats(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name_order: Literal["given_family", "family_given"]
    date_format: str = Field(min_length=1)
    time_format: Literal["12h", "24h"]
    datetime_format: str = Field(min_length=1)
    # Issue #3141: the title written before a physician's name (HumanName.prefix);
    # empty when the country writes none.
    physician_name_prefix: str

    def name_parts(self, family: str, given: str) -> tuple[str, str]:
        """``(family, given)`` in the country's written order (``name_order``)."""
        return (family, given) if self.name_order == "family_given" else (given, family)


def _root_keys(section: str) -> frozenset[str]:
    return frozenset((load_data_yaml(_ROOT) or {}).get(section) or {})


class CountryProfile(BaseModel):
    """One country's validated profile (spec §3.2)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str = Field(pattern=r"^[A-Z]{2}$")
    language: str = Field(pattern=r"^[a-z]{2}$")
    timezone: str = Field(pattern=r"^(Z|[+-]\d{2}:\d{2})$")
    code_systems: dict[str, str]
    fhir_profiles: tuple[str, ...]
    features: dict[str, bool]
    formats: _Formats
    implementations: dict[str, str]

    @field_validator("code_systems")
    @classmethod
    def _code_systems_exist(cls, value: dict[str, str]) -> dict[str, str]:
        from clinosim.codes import system_keys

        if set(value) != set(CODE_SYSTEM_KINDS):
            raise ValueError(f"code_systems kinds must be exactly {sorted(CODE_SYSTEM_KINDS)}, got {sorted(value)}")
        unknown = {k: v for k, v in value.items() if v not in system_keys()}
        if unknown:
            raise ValueError(f"code systems not in clinosim.codes: {unknown}")
        return value

    @field_validator("fhir_profiles")
    @classmethod
    def _known_profiles(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        unknown = sorted(set(value) - FHIR_PROFILES)
        if unknown:
            raise ValueError(f"unknown FHIR profiles {unknown}; known: {sorted(FHIR_PROFILES)}")
        return value

    @model_validator(mode="after")
    def _root_vocabulary(self) -> CountryProfile:
        # A country may not invent a feature or an implementation kind: the
        # root declares the vocabulary.
        for section, names in (("features", self.features), ("implementations", self.implementations)):
            extra = sorted(set(names) - _root_keys(section))
            if extra:
                raise ValueError(f"{section} not declared in the root profile: {extra}")
        return self

    @property
    def language_tag(self) -> str:
        """BCP 47 tag of the output language in this country (``en-US``, ``ja-JP``)."""
        return f"{self.language}-{self.code}"

    def uses(self, profile_name: str) -> bool:
        """Whether output applies the FHIR profile ``profile_name``."""
        if profile_name not in FHIR_PROFILES:
            raise KeyError(f"unknown FHIR profile {profile_name!r}; known: {sorted(FHIR_PROFILES)}")
        return profile_name in self.fhir_profiles

    def feature(self, name: str) -> bool:
        """Whether the country feature ``name`` is on."""
        if name not in self.features:
            raise KeyError(f"unknown country feature {name!r}; known: {sorted(self.features)}")
        return self.features[name]

    def code_system(self, kind: str) -> str:
        """The code-system key the country uses for ``kind``."""
        if kind not in self.code_systems:
            raise KeyError(f"unknown code-system kind {kind!r}; known: {sorted(self.code_systems)}")
        return self.code_systems[kind]

    def implementation(self, kind: str) -> str:
        """The implementation name the country selects for ``kind``."""
        if kind not in self.implementations:
            raise KeyError(f"unknown implementation kind {kind!r}; known: {sorted(self.implementations)}")
        return self.implementations[kind]


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """``override`` over ``base``: maps merge key by key, lists and scalars
    replace (spec §3.1). Neither input is modified."""
    out = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


@cache
def supported_countries() -> tuple[str, ...]:
    """Upper-case codes of the countries that have a profile (``_root`` and
    ``_template`` are not countries)."""
    return tuple(
        sorted(p.parent.name.upper() for p in _LOCALE.glob(f"*/{_PROFILE_FILE}") if not p.parent.name.startswith("_"))
    )


# Legacy spellings the simulator still carries ("japan" is the disease-YAML
# locale key, Issue #2838), mapped to the ISO code.
_LEGACY_SPELLINGS = {"JAPAN": "JP"}


def _normalise(country: str) -> str:
    code = str(country or "").strip().upper()
    code = _LEGACY_SPELLINGS.get(code, code)
    if code not in supported_countries():
        raise KeyError(f"no country profile for {country!r}; supported: {list(supported_countries())}")
    return code


def load_profile_data(country: str) -> dict[str, Any]:
    """The merged (unvalidated) profile data of ``country``."""
    code = _normalise(country)
    root = load_data_yaml(_ROOT) or {}
    own = load_data_yaml(_LOCALE / code.lower() / _PROFILE_FILE) or {}
    return deep_merge(root, own)


# kind -> name -> callable
_REGISTRY: dict[str, dict[str, Callable[..., Any]]] = {}


def register_implementation(kind: str, name: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Register the decorated callable as implementation ``name`` of ``kind``.
    Registering a name twice fails."""

    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        names = _REGISTRY.setdefault(kind, {})
        if name in names and names[name] is not fn:
            raise ValueError(f"implementation {kind}/{name} is already registered")
        names[name] = fn
        return fn

    return decorator


def _import_implementations() -> None:
    for module in IMPLEMENTATION_MODULES:
        importlib.import_module(module)


def validate_implementations(profile: CountryProfile) -> None:
    """Fail when the profile names an implementation nobody registered."""
    _import_implementations()
    missing = {kind: name for kind, name in profile.implementations.items() if name not in _REGISTRY.get(kind, {})}
    if missing:
        raise ValueError(f"country {profile.code}: unregistered implementations {missing}")


@lru_cache(maxsize=8)
def _profile(code: str) -> CountryProfile:
    profile = CountryProfile.model_validate(load_profile_data(code))
    if profile.code != code:
        raise ValueError(f"locale/{code.lower()}/{_PROFILE_FILE} declares code {profile.code!r}")
    validate_implementations(profile)
    return profile


def country_profile(country: str) -> CountryProfile:
    """The validated, cached profile of ``country`` (spec §3.3). Unknown
    countries raise ``KeyError``."""
    return _profile(_normalise(country))


def implementation(kind: str, country: str) -> Callable[..., Any]:
    """The callable registered under the name ``country``'s profile selects."""
    name = country_profile(country).implementation(kind)
    return _REGISTRY[kind][name]
