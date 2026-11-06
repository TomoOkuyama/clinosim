"""Code status (resuscitation status) assignment (AD-55 Base). Pure + seeded."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, field_validator

from clinosim.age_bands import find_age_band, parse_closed_age_band
from clinosim.codes import code_exists
from clinosim.datafiles import load_data_yaml
from clinosim.modules._shared import is_jp, is_us, normalize_probabilities

_HERE = Path(__file__).resolve().parent
_REF_DIR = _HERE / "reference_data"
_LOCALE = _HERE.parents[1] / "locale"


class _Tier(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(min_length=1)
    snomed: str
    en: str = Field(min_length=1)
    ja: str = ""

    @field_validator("snomed")
    @classmethod
    def _registered(cls, code: str) -> str:
        return _registered_snomed(code)


class _CodeStatusConfig(BaseModel):
    """Shape of code_status.yaml (Issue #2760)."""

    model_config = ConfigDict(extra="forbid")

    metadata: dict[str, Any] = Field(default_factory=dict)
    observable_snomed: str
    age_bands: list[str] = Field(min_length=1)
    tiers: list[_Tier] = Field(min_length=1)

    @field_validator("observable_snomed")
    @classmethod
    def _registered(cls, code: str) -> str:
        return _registered_snomed(code)

    @field_validator("age_bands")
    @classmethod
    def _bands(cls, bands: list[str]) -> list[str]:
        for band in bands:
            parse_closed_age_band(band)
        return bands


def _registered_snomed(code: str) -> str:
    if not code_exists("snomed-ct", code, exact=True):
        raise ValueError(f"code_status.yaml SNOMED {code!r} not in codes/data/snomed-ct.yaml")
    return code


@lru_cache(maxsize=1)
def load_reference() -> dict:
    data = load_data_yaml(_REF_DIR / "code_status.yaml") or {}
    _CodeStatusConfig.model_validate(data)
    return data


@lru_cache(maxsize=2)
def load_rates(country: str) -> dict:
    """Load code-status rates for ``country``. Returns ``{}`` for unsupported
    countries rather than silently falling back to US data (locale-loader
    unsupported-country contract, 2026-07-02 grand design review)."""
    if not (is_us(country) or is_jp(country)):
        return {}
    key = "jp" if is_jp(country) else "us"
    return (load_data_yaml(_LOCALE / key / "code_status_rates.yaml") or {}).get("weights", {})


def _age_band(age: int, bands: list[str]) -> str:
    band = find_age_band(bands, age)
    return band if band is not None else bands[-1]


def assign_code_status(age: int, context: str, country: str, rng: np.random.Generator) -> str:
    """Return the SNOMED code of the sampled tier for (age, context).

    context: "routine" | "icu" | "terminal". Deterministic for a given rng.
    Returns ``""`` (no code status) for a country without rates.
    """
    ref = load_reference()
    rates = load_rates(country)
    if not rates:
        return ""
    tiers = ref["tiers"]
    band = _age_band(int(age), ref["age_bands"])
    weights = rates.get(context, rates["routine"]).get(band)
    if not weights:
        weights = rates["routine"][ref["age_bands"][-1]]
    idx = int(rng.choice(len(tiers), p=normalize_probabilities(weights, fallback="raise")))
    return str(tiers[idx]["snomed"])
