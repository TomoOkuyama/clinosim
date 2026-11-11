"""JP 要介護度 (long-term-care need level) assignment (AD-55 Base). Pure + seeded."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, field_validator

from clinosim.age_bands import find_age_band_or_last, parse_closed_age_band
from clinosim.country_profile import country_profile
from clinosim.datafiles import load_data_yaml
from clinosim.modules._shared import normalize_probabilities

_HERE = Path(__file__).resolve().parent
_REF_DIR = _HERE / "reference_data"
_LOCALE = _HERE.parents[1] / "locale"


class _EligibilityGates(BaseModel):
    model_config = ConfigDict(extra="forbid")

    primary_insured_min_age: int = Field(ge=0)
    secondary_insured_min_age: int = Field(ge=0)
    secondary_designated_condition_codes: list[str] = Field(min_length=1)

    @field_validator("secondary_designated_condition_codes")
    @classmethod
    def _prefixes(cls, codes: list[str]) -> list[str]:
        if any(not str(c).strip() for c in codes):
            raise ValueError("care_level.yaml: empty ICD prefix in secondary_designated_condition_codes")
        return codes


class _CareLevelConfig(BaseModel):
    """Shape of care_level.yaml (Issue #2760)."""

    model_config = ConfigDict(extra="forbid")

    metadata: dict[str, Any] = Field(default_factory=dict)
    levels: list[str] = Field(min_length=1)
    age_bands: list[str] = Field(min_length=1)
    eligibility_gates: _EligibilityGates

    @field_validator("age_bands")
    @classmethod
    def _bands(cls, bands: list[str]) -> list[str]:
        for band in bands:
            parse_closed_age_band(band)
        return bands


@lru_cache(maxsize=1)
def load_reference() -> dict:
    data = load_data_yaml(_REF_DIR / "care_level.yaml") or {}
    _CareLevelConfig.model_validate(data)
    return data


@lru_cache(maxsize=2)
def load_rates(country: str) -> dict:
    """Load care-level rates for ``country``. Returns ``{}`` when the country
    profile has the ``care_level`` feature off (no-op path; Issue #3143) —
    care_level is currently JP-only, but the signature matches immunization /
    family_history / code_status so future locale additions slot in without
    API churn."""
    if not country_profile(country).feature("care_level"):
        return {}
    return (load_data_yaml(_LOCALE / "jp" / "care_level_rates.yaml") or {}).get("weights", {})


def patient_qualifies_for_secondary_ltci(chronic_condition_codes: list[str]) -> bool:
    """Return True when at least one code matches a 第2号被保険者 相当疾病 prefix.

    Called by the care-level enricher for 40-64-year-old patients (Issue
    #940). Codes are compared by ``startswith`` so ``E11.9`` matches an
    ``E11`` prefix and ``I63.9`` matches ``I63``. Empty codes and empty
    prefixes are ignored.

    The prefix list lives in ``reference_data/care_level.yaml`` under
    ``eligibility_gates.secondary_designated_condition_codes`` — see that
    file for sourcing and the interim overlap with clinosim's chronic
    disease catalogue.
    """
    prefixes = tuple(
        p
        for p in (load_reference().get("eligibility_gates") or {}).get("secondary_designated_condition_codes", [])
        if p
    )
    if not prefixes:
        return False
    for code in chronic_condition_codes:
        if not code:
            continue
        if code.startswith(prefixes):
            return True
    return False


def assign_care_level(age: int, country: str, rng: np.random.Generator) -> str:
    """Return the jp-care-level code (or "" for independent / a country without
    the ``care_level`` feature). Deterministic."""
    if not country_profile(country).feature("care_level"):
        return ""
    ref = load_reference()
    levels = ref["levels"]
    weights = list(load_rates(country).get(find_age_band_or_last(ref["age_bands"], int(age)), []))
    if not weights or sum(weights) <= 0:
        return ""
    # fallback="raise" is defense-in-depth; the early-exit above guards zero-sum first
    probs = normalize_probabilities(weights, fallback="raise")
    code = levels[int(rng.choice(len(levels), p=probs))]
    return "" if code == "independent" else code
