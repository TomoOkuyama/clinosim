"""Demographics-sampling cluster.

Extracted verbatim from ``clinosim/modules/population/engine.py`` as
step C3b of the full-review Phase C engine split (CRITICAL C3).
Behavior is byte-identical — ``engine.py`` re-exports these names so
every call site stays intact.

Several helpers derive person-level attributes from a stable sha256(id)
hash (not the master RNG); the RNG-consuming helpers thread an
``np.random.Generator`` through without reading any shared state.
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

import numpy as np

from clinosim.modules._shared import normalize_probabilities
from clinosim.modules.population._household_thresholds import (
    BLOOD_TYPE_DEFAULT_DISTRIBUTION,
    SEX_RATIO_MALE_DEFAULT,
)
from clinosim.modules.population._population_thresholds import (
    CARE_SEEKING_THRESHOLD_MEAN_DEFAULT,
)

if TYPE_CHECKING:
    from clinosim.modules.population.engine import PersonRecord


def _load_demographics(country: str) -> dict:
    """Load demographic data from locale."""
    from clinosim.locale.loader import load_demographics

    return load_demographics(country)


def _parse_age_distribution(demo: dict) -> tuple[list[tuple[int, int]], list[float]]:
    """Parse age_distribution from demographics YAML into bands and probs."""
    raw = demo.get("age_distribution", {})
    bands: list[tuple[int, int]] = []
    probs: list[float] = []
    for key, val in raw.items():
        lo, hi = key.split("-")
        bands.append((int(lo), int(hi)))
        probs.append(float(val))
    return bands, probs


def _disease_monthly_rate_from_locale(
    person: PersonRecord,
    month: int,
    age_rates: dict | list[tuple[int, float]],
    sex_ratio_female: float,
    seasonal: dict,
    risk_multipliers: dict,
) -> float:
    """Calculate monthly disease rate from locale epidemiology data.

    ``age_rates`` accepts either the raw YAML dict shape or the
    pre-sorted ``[(age_lo, base_rate), ...]`` list produced once per
    disease by the ``generate_monthly_events`` precompute block.
    Dict-shape callers (unit tests, ad-hoc rate samplers) keep working
    unchanged.
    """
    rate = 0.0
    if isinstance(age_rates, list):
        for age_lo, r in age_rates:
            if person.age >= age_lo:
                rate = r
    else:
        for age_str, r in sorted(age_rates.items(), key=lambda x: int(x[0])):
            if person.age >= int(age_str):
                rate = float(r)
    if person.sex == "F":
        rate *= sex_ratio_female
    monthly = (rate / 100_000) / 12
    seasonal_mod = seasonal.get(month, seasonal.get(str(month), 1.0))
    monthly *= float(seasonal_mod)
    for code, mult in risk_multipliers.items():
        if code in person.chronic_conditions:
            monthly *= float(mult)
    return monthly


def _sample_age_band(demo: dict, rng: np.random.Generator) -> tuple[int, int]:
    bands, probs = _parse_age_distribution(demo)
    idx = int(rng.choice(len(bands), p=normalize_probabilities(probs, fallback="raise")))
    return bands[idx]


def _sex_ratio_male_probability(demo: dict, age: int) -> float:
    """Return P(male) for a person of the given age, per the demographics YAML.

    Lookup order (Issue #741):
      1. ``sex_ratio.age_conditional[<band>]`` where <band> covers ``age``
      2. ``sex_ratio.male`` (top-level fallback)
      3. ``SEX_RATIO_MALE_DEFAULT`` (constant)

    Bands are inclusive ranges declared as ``"lo-hi"`` strings. The block
    is optional; locales that omit it collapse to the single-probability
    behaviour (RNG-shape neutral — the caller still issues one
    ``rng.random()`` per person regardless of which branch resolves).
    """
    sr = demo.get("sex_ratio") or {}
    age_cond = sr.get("age_conditional") or {}
    for band_str, prob in age_cond.items():
        lo_s, hi_s = str(band_str).split("-")
        if int(lo_s) <= age <= int(hi_s):
            return float(prob)
    return float(sr.get("male", SEX_RATIO_MALE_DEFAULT))


def _care_seeking_threshold_mean(demo: dict, age: int) -> float:
    """Return the care-seeking severity-threshold mean for a person of the given age.

    Lookup order (Issue #922):
      1. ``care_seeking.age_conditional[<band>]`` where <band> covers ``age``
         (bands are inclusive ``"lo-hi"`` strings; the ``"lo+"`` shorthand
         is also accepted for readability of open-ended elderly bands)
      2. ``care_seeking.threshold_mean`` (top-level fallback — the
         pre-Issue-#922 behaviour)
      3. ``CARE_SEEKING_THRESHOLD_MEAN_DEFAULT`` (constant)

    RNG-shape neutral — the caller still issues one ``rng.normal(mean, sd)``
    per person regardless of which branch resolves; only the ``mean``
    argument changes, so the RNG cursor advances identically for every
    seed.
    """
    cs = demo.get("care_seeking") or {}
    age_cond = cs.get("age_conditional") or {}
    for band_str, val in age_cond.items():
        raw = str(band_str)
        if raw.endswith("+"):
            lo_s = raw[:-1]
            if age >= int(lo_s):
                return float(val)
            continue
        lo_s, hi_s = raw.split("-")
        if int(lo_s) <= age <= int(hi_s):
            return float(val)
    return float(cs.get("threshold_mean", CARE_SEEKING_THRESHOLD_MEAN_DEFAULT))


_RH_POSITIVE_FRACTION: dict[str, float] = {
    "JP": 0.995,
    "US": 0.85,
}


def _derive_race(person_id: str, demo: dict) -> str:
    """Return the OMB race category for a person, derived from a stable
    hash of ``person_id`` + the locale ``race_distribution``. SHA-based
    (not RNG) so this field can be added post-facto without shifting
    any downstream RNG cursor — memoize / F4 byte-identical guarantee
    preserved. Returns ``""`` when the locale has no race_distribution
    (e.g. JP), which matches the pre-#1581 activator fallback.
    """
    dist = (demo or {}).get("race_distribution") or {}
    if not dist:
        return ""
    keys = list(dist.keys())
    weights = normalize_probabilities([float(dist[k]) for k in keys], fallback="raise")
    h = hashlib.sha256(f"{person_id}|race|v1".encode()).digest()
    quantile = int.from_bytes(h[:4], "big") / (2**32)
    acc = 0.0
    for key, weight in zip(keys, weights, strict=False):
        acc += float(weight)
        if quantile < acc:
            return key
    return keys[-1]


def _derive_ethnicity(person_id: str, demo: dict) -> str:
    """Return the hispanic / not_hispanic ethnicity category, same
    determinism contract as :func:`_derive_race`. Returns ``""`` when
    the locale has no ethnicity_distribution.
    """
    dist = (demo or {}).get("ethnicity_distribution") or {}
    if not dist:
        return ""
    keys = list(dist.keys())
    weights = normalize_probabilities([float(dist[k]) for k in keys], fallback="raise")
    h = hashlib.sha256(f"{person_id}|ethnicity|v1".encode()).digest()
    quantile = int.from_bytes(h[:4], "big") / (2**32)
    acc = 0.0
    for key, weight in zip(keys, weights, strict=False):
        acc += float(weight)
        if quantile < acc:
            return key
    return keys[-1]


def _derive_rh_factor(person_id: str, country: str) -> str:
    """Return "+" (RhD positive) or "-" (negative), derived from a stable
    hash of ``person_id`` so the choice is deterministic per person AND
    does not consume the master RNG (memoize / F4 byte-identical guarantee
    preserved when this field was added post-facto).

    Country selects the Rh-positive fraction: JP 99.5%, US 85%.
    Unknown countries fall through to JP default (conservative — Rh-
    negative is the clinically-actionable state; over-emitting Rh+ is
    a lower-cost failure mode for a synthetic dataset).
    """
    frac = _RH_POSITIVE_FRACTION.get("US" if country.upper() == "US" else "JP", 0.995)
    h = hashlib.sha256(f"{person_id}|rh".encode()).digest()
    quantile = int.from_bytes(h[:2], "big") / 65535.0
    return "+" if quantile < frac else "-"


def _sample_blood_type(demo: dict, rng: np.random.Generator) -> str:
    """Sample blood type using weighted probability from demographics.

    Routes YAML-sourced weights through normalize_probabilities(fallback="raise")
    to handle floating-point summation artifacts (e.g., 0.40+0.30+0.20+0.10
    sums to 0.9999999999999999 in float64, not exactly 1.0).
    """
    bt = demo.get("blood_type", BLOOD_TYPE_DEFAULT_DISTRIBUTION)
    keys = list(bt.keys())
    weights = normalize_probabilities([bt[k] for k in keys], fallback="raise")
    idx = int(rng.choice(len(keys), p=weights))
    return keys[idx]
