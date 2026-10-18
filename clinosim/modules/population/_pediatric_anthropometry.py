"""Pediatric anthropometric lookup helpers.

Resolves per-age / per-sex / per-country median height and BMI for
Layer 1 (population) and Layer 2 (patient activator) sampling so that
pediatric persons stop inheriting adult BMI / height distributions.

Pre-fix the population generator sampled BMI from an adult-only
distribution (US male mean ≈ 26.3, female ≈ 25.5) and the activator
sampled height from an adult-only distribution (170 / 157.5 cm) for
every age. A 4-year-old would therefore land on BMI ~ 26 and height
~ 170 cm, giving a stored weight ~ 75 kg — physically impossible.

The medians come from the shared yaml at
``locale/shared/anthropometric_reference.yaml`` (CDC growth charts for
US, MHLW / MEXT for JP, both already consumed by the FHIR anthropometric
Observation emit). The sampling SD is kept small — a true growth-chart
±1 z-band is wider at the tails, but Layer 1 only needs enough spread
to avoid every same-age child landing on identical BMI; per-encounter
variation comes from the FHIR anthropometric emit noise, not here.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from clinosim.modules._shared import is_jp

_REFERENCE_PATH = Path(__file__).resolve().parents[2] / "locale" / "shared" / "anthropometric_reference.yaml"

# Age gate: strictly below ``PEDIATRIC_UPPER_AGE_EXCLUSIVE`` → pediatric
# branch. Set to ``adult_path_min_age_years`` in the yaml (default 18) so
# the Layer-1/2 sampling boundary matches the FHIR-emit boundary.
_DEFAULT_PEDIATRIC_UPPER_AGE = 18

# Fallback SDs when the yaml carries no explicit ``pediatric_sampling``
# section. Chosen conservatively (height ±3 cm, BMI ±1.0) to produce
# visible within-cohort variation without approaching clinically
# implausible outliers that the growth-chart ±1 z-band would allow.
_FALLBACK_HEIGHT_SD_CM = 3.0
_FALLBACK_BMI_SD = 1.0


@lru_cache(maxsize=1)
def _load_reference() -> dict[str, Any]:
    with _REFERENCE_PATH.open() as f:
        return yaml.safe_load(f) or {}


def pediatric_upper_age() -> int:
    """Inclusive-lower-bound age at which the adult-sampling path takes
    over. Below this age the pediatric growth-chart medians apply."""
    ref = _load_reference()
    return int(ref.get("adult_path_min_age_years", _DEFAULT_PEDIATRIC_UPPER_AGE))


def _lookup_median(country: str, sex: str, age_years: int) -> dict[str, float] | None:
    ref = _load_reference()
    tables = (ref.get("pediatric_growth") or {}).get("JP" if is_jp(country) else "US") or {}
    sex_key = "male" if str(sex or "").upper().startswith("M") else "female"
    row = (tables.get(sex_key) or {}).get(int(age_years))
    if not row:
        return None
    return {"height": float(row["height"]), "weight": float(row["weight"])}


def _sampling_sd() -> tuple[float, float]:
    """Return (height_cm_sd, bmi_sd) from the yaml, falling back to
    conservative defaults when the section is absent."""
    ref = _load_reference()
    cfg = ref.get("pediatric_sampling") or {}
    return (
        float(cfg.get("height_cm_sd", _FALLBACK_HEIGHT_SD_CM)),
        float(cfg.get("bmi_sd", _FALLBACK_BMI_SD)),
    )


def pediatric_bmi_params(country: str, sex: str, age_years: int) -> dict[str, float] | None:
    """Return ``{"mean": …, "std": …}`` for the pediatric BMI distribution
    at ``(country, sex, age)`` — mean derived from the growth-chart
    median ``weight / (height/100)^2``. Returns ``None`` when the age
    falls outside the growth-chart range (callers then fall back to the
    adult path)."""
    med = _lookup_median(country, sex, age_years)
    if med is None:
        return None
    h_m = med["height"] / 100.0
    bmi_mean = med["weight"] / (h_m * h_m)
    _, bmi_sd = _sampling_sd()
    return {"mean": bmi_mean, "std": bmi_sd}


def pediatric_height_params(country: str, sex: str, age_years: int) -> dict[str, float] | None:
    """Return ``{"mean": …, "std": …}`` for the pediatric height
    distribution. Returns ``None`` when the age falls outside the
    growth-chart range."""
    med = _lookup_median(country, sex, age_years)
    if med is None:
        return None
    ht_sd, _ = _sampling_sd()
    return {"mean": med["height"], "std": ht_sd}
