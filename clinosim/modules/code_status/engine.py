"""Code status (resuscitation status) assignment (AD-55 Base). Pure + seeded."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import numpy as np
import yaml

from clinosim.modules._shared import normalize_probabilities

_HERE = Path(__file__).resolve().parent
_REF_DIR = _HERE / "reference_data"
_LOCALE = _HERE.parents[1] / "locale"


@lru_cache(maxsize=1)
def load_reference() -> dict:
    with open(_REF_DIR / "code_status.yaml") as f:
        return yaml.safe_load(f) or {}


@lru_cache(maxsize=2)
def load_rates(country: str) -> dict:
    key = "jp" if str(country).upper() == "JP" else "us"
    with open(_LOCALE / key / "code_status_rates.yaml") as f:
        return (yaml.safe_load(f) or {}).get("weights", {})


def _age_band(age: int, bands: list[str]) -> str:
    for band in bands:
        lo, hi = (int(x) for x in band.split("-"))
        if lo <= age <= hi:
            return band
    return bands[-1]


def assign_code_status(age: int, context: str, country: str,
                       rng: np.random.Generator) -> str:
    """Return the SNOMED code of the sampled tier for (age, context).

    context: "routine" | "icu" | "terminal". Deterministic for a given rng.
    """
    ref = load_reference()
    rates = load_rates(country)
    tiers = ref["tiers"]
    band = _age_band(int(age), ref["age_bands"])
    weights = rates.get(context, rates["routine"]).get(band)
    if not weights:
        weights = rates["routine"][ref["age_bands"][-1]]
    idx = int(rng.choice(len(tiers), p=normalize_probabilities(weights)))
    return str(tiers[idx]["snomed"])
