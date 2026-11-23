"""Code status (resuscitation status) assignment (AD-55 Base). Pure + seeded."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, field_validator

from clinosim import determinism
from clinosim.age_bands import find_age_band_or_last, parse_closed_age_band
from clinosim.codes import code_exists
from clinosim.datafiles import load_data_yaml
from clinosim.modules._shared import is_jp, is_us, normalize_probabilities
from clinosim.seeding import airway_declined_seed

_HERE = Path(__file__).resolve().parent
_REF_DIR = _HERE / "reference_data"
_LOCALE = _HERE.parents[1] / "locale"


class _Tier(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(min_length=1)
    snomed: str
    en: str = Field(min_length=1)
    ja: str = ""
    declines_intubation: bool = False

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


def _tier_weights(age: int, context: str, rates: dict, ref: dict) -> list[float]:
    band = find_age_band_or_last(ref["age_bands"], int(age))
    weights = rates.get(context, rates["routine"]).get(band)
    if not weights:
        weights = rates["routine"][ref["age_bands"][-1]]
    return [float(w) for w in weights]


def airway_declined_probability(age: int, country: str) -> float:
    """Probability that a patient whose airway would need securing has decided
    against intubation (Issue #3551): the share of the ICU-context tier weights of
    the tiers flagged ``declines_intubation``. ``0.0`` for a country without rates."""
    ref = load_reference()
    rates = load_rates(country)
    if not rates:
        return 0.0
    weights = _tier_weights(age, "icu", rates, ref)
    total = sum(weights)
    declining = sum(w for w, tier in zip(weights, ref["tiers"], strict=True) if tier.get("declines_intubation"))
    return declining / total if total > 0 else 0.0


def airway_declined(age: int, country: str, encounter_id: str) -> bool:
    """Whether the patient of ``encounter_id`` has decided against intubation.

    Decided before the airway escalation of the stay, from a sub-RNG seeded by the
    encounter id alone, so the stay's own RNG and the enricher's draw are not read
    or shifted, and the result is the same wherever it is asked."""
    p = airway_declined_probability(age, country)
    if p <= 0.0:
        return False
    return bool(determinism.default_rng(airway_declined_seed(encounter_id)).random() < p)


def assign_tier(age: int, context: str, country: str, rng: np.random.Generator, *, airway: str = "") -> dict | None:
    """The sampled tier for (age, context), or ``None`` for a country without rates.

    ``airway`` ties the tier to the stay's airway decision (Issue #3551), still with
    one draw: ``"declined"`` samples among the tiers that decline intubation,
    ``"intubated"`` samples among the others (a patient intubated in the stay did not
    decline intubation). An empty restricted weight set falls back to the ICU-context
    weights."""
    ref = load_reference()
    rates = load_rates(country)
    if not rates:
        return None
    tiers = ref["tiers"]
    weights = _tier_weights(age, context, rates, ref)
    if airway:
        want = airway == "declined"
        mask = [bool(t.get("declines_intubation")) == want for t in tiers]
        restricted = [w if m else 0.0 for w, m in zip(weights, mask, strict=True)]
        if sum(restricted) <= 0:
            weights = _tier_weights(age, "icu", rates, ref)
            restricted = [w if m else 0.0 for w, m in zip(weights, mask, strict=True)]
        weights = restricted
    idx = int(rng.choice(len(tiers), p=normalize_probabilities(weights, fallback="raise")))
    return dict(tiers[idx])


def assign_code_status(age: int, context: str, country: str, rng: np.random.Generator, *, airway: str = "") -> str:
    """Return the SNOMED code of the sampled tier for (age, context).

    context: "routine" | "icu" | "terminal". Deterministic for a given rng.
    Returns ``""`` (no code status) for a country without rates. ``airway``: see
    :func:`assign_tier`.
    """
    tier = assign_tier(age, context, country, rng, airway=airway)
    return str(tier["snomed"]) if tier else ""
