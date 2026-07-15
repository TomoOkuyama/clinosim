"""JP 要介護度 (long-term-care need level) assignment (AD-55 Base). Pure + seeded."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import numpy as np
import yaml

from clinosim.modules._shared import is_jp, normalize_probabilities

_HERE = Path(__file__).resolve().parent
_REF_DIR = _HERE / "reference_data"
_LOCALE = _HERE.parents[1] / "locale"


@lru_cache(maxsize=1)
def load_reference() -> dict:
    with open(_REF_DIR / "care_level.yaml") as f:
        return yaml.safe_load(f) or {}


@lru_cache(maxsize=2)
def load_rates(country: str = "JP") -> dict:
    """Load care-level rates for ``country``. Returns ``{}`` for non-JP
    (no-op path) — care_level is currently JP-only, but the signature
    matches immunization / family_history / code_status so future locale
    additions slot in without API churn."""
    if not is_jp(country):
        return {}
    with open(_LOCALE / "jp" / "care_level_rates.yaml") as f:
        return (yaml.safe_load(f) or {}).get("weights", {})


def _age_band(age: int, bands: list[str]) -> str:
    for band in bands:
        lo, hi = (int(x) for x in band.split("-"))
        if lo <= age <= hi:
            return band
    return bands[-1]


def assign_care_level(age: int, country: str, rng: np.random.Generator) -> str:
    """Return the jp-care-level code (or "" for independent / non-JP). Deterministic."""
    if not is_jp(country):
        return ""
    ref = load_reference()
    levels = ref["levels"]
    weights = list(load_rates().get(_age_band(int(age), ref["age_bands"]), []))
    if not weights or sum(weights) <= 0:
        return ""
    # fallback="raise" is defense-in-depth; the early-exit above guards zero-sum first
    probs = normalize_probabilities(weights, fallback="raise")
    code = levels[int(rng.choice(len(levels), p=probs))]
    return "" if code == "independent" else code
