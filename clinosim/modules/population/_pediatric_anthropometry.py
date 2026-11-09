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
``modules/population/reference_data/anthropometric_reference.yaml`` (CDC growth charts for
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

from pydantic import BaseModel, ConfigDict, Field, StrictFloat, StrictInt, model_validator

from clinosim.datafiles import load_validated_yaml
from clinosim.modules._shared import is_jp

_REFERENCE_PATH = Path(__file__).resolve().parent / "reference_data" / "anthropometric_reference.yaml"

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


class _Range(BaseModel):
    model_config = ConfigDict(extra="forbid")
    min: StrictFloat | StrictInt
    max: StrictFloat | StrictInt

    @model_validator(mode="after")
    def _ordered(self) -> _Range:
        if not self.min < self.max:
            raise ValueError(f"range min {self.min} must be below max {self.max}")
        return self


class _Clamps(BaseModel):
    model_config = ConfigDict(extra="forbid")
    height_cm: _Range
    weight_kg: _Range
    bmi: _Range
    head_circumference_cm: _Range


class _EncounterNoise(BaseModel):
    model_config = ConfigDict(extra="forbid")
    weight_kg_sd: StrictFloat | StrictInt = Field(ge=0)
    head_circumference_cm_sd: StrictFloat | StrictInt = Field(ge=0)
    pediatric_weight_cv: StrictFloat | StrictInt = Field(ge=0, lt=0.1)
    pediatric_height_cm_sd: StrictFloat | StrictInt = Field(ge=0)


class _GrowthVariation(BaseModel):
    """Per-child spread around the growth medians (Issue #2876)."""

    model_config = ConfigDict(extra="forbid")
    height_cv: StrictFloat | StrictInt = Field(gt=0, lt=0.2)
    weight_cv: StrictFloat | StrictInt = Field(gt=0, lt=0.4)
    head_circumference_cv: StrictFloat | StrictInt = Field(gt=0, lt=0.2)
    shared_size_correlation: StrictFloat | StrictInt = Field(ge=0, le=1)
    z_limit: StrictFloat | StrictInt = Field(gt=0, le=4)

    @model_validator(mode="after")
    def _positive_at_tail(self) -> _GrowthVariation:
        for cv in (self.height_cv, self.weight_cv, self.head_circumference_cv):
            if cv * self.z_limit >= 1:
                raise ValueError(f"cv {cv} x z_limit {self.z_limit} would reach a non-positive measurement")
        return self


class _GrowthRow(BaseModel):
    model_config = ConfigDict(extra="forbid")
    height: StrictFloat | StrictInt = Field(gt=0)
    weight: StrictFloat | StrictInt = Field(gt=0)
    # Recorded up to head_circumference_max_age_years (checked by the file model).
    head_circumference: StrictFloat | StrictInt | None = Field(default=None, gt=0)


class _BySex(BaseModel):
    model_config = ConfigDict(extra="forbid")
    male: dict[int, _GrowthRow] = Field(min_length=1)
    female: dict[int, _GrowthRow] = Field(min_length=1)


class _Sampling(BaseModel):
    model_config = ConfigDict(extra="forbid")
    height_cm_sd: StrictFloat | StrictInt = Field(gt=0)
    bmi_sd: StrictFloat | StrictInt = Field(gt=0)


class _AnthropometricReference(BaseModel):
    """Shape of ``anthropometric_reference.yaml`` (configuration spec): the
    yearly growth medians cover every pediatric age of both countries and
    sexes, and each median lies inside the clamps."""

    model_config = ConfigDict(extra="forbid")
    clamps: _Clamps
    per_encounter_noise: _EncounterNoise
    pediatric_growth_variation: _GrowthVariation
    pediatric_growth_infant: _BySex  # keyed by age in months
    pediatric_growth: dict[str, _BySex]  # country -> keyed by age in years
    head_circumference_max_age_years: StrictInt = Field(ge=0)
    adult_path_min_age_years: StrictInt = Field(gt=0)
    pediatric_sampling: _Sampling

    @model_validator(mode="after")
    def _covers_pediatric_ages(self) -> _AnthropometricReference:
        if set(self.pediatric_growth) != {"US", "JP"}:
            raise ValueError(f"pediatric_growth countries must be US and JP, got {sorted(self.pediatric_growth)}")
        ages = set(range(self.adult_path_min_age_years))
        c = self.clamps
        tables = [(f"pediatric_growth.{k}", v, True) for k, v in self.pediatric_growth.items()]
        tables.append(("pediatric_growth_infant", self.pediatric_growth_infant, False))
        for where, by_sex, yearly in tables:
            for sex in ("male", "female"):
                rows = getattr(by_sex, sex)
                if yearly and set(rows) != ages:
                    raise ValueError(f"{where}.{sex}: ages must be 0..{max(ages)}")
                for age, r in rows.items():
                    if yearly and age <= self.head_circumference_max_age_years and r.head_circumference is None:
                        raise ValueError(f"{where}.{sex} age {age}: head_circumference required")
                    hc_ok = r.head_circumference is None or (
                        c.head_circumference_cm.min <= r.head_circumference <= c.head_circumference_cm.max
                    )
                    if not (
                        c.height_cm.min <= r.height <= c.height_cm.max
                        and c.weight_kg.min <= r.weight <= c.weight_kg.max
                        and hc_ok
                    ):
                        raise ValueError(f"{where}.{sex} age {age}: growth median lies outside the clamps")
        return self


@lru_cache(maxsize=1)
def load_anthropometric_reference() -> dict[str, Any]:
    """``anthropometric_reference.yaml``, validated by ``_AnthropometricReference``.
    The one loader of the file (the FHIR anthropometrics builder reads it too)."""
    return load_validated_yaml(_REFERENCE_PATH, _AnthropometricReference)


def _load_reference() -> dict[str, Any]:
    return load_anthropometric_reference()


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


def pediatric_snapshot_profile(country: str, sex: str, age_years: int) -> dict[str, float] | None:
    """Return the growth-chart p50 anthropometry profile at
    ``(country, sex, age)`` as ``{"height_cm": …, "weight_kg": …,
    "bmi": …}``. Pure lookup — no RNG draw. Returns ``None`` when the
    age falls outside the pediatric growth-chart range.

    Intended for CIF-write-time snapshot updates on mid-sim-born
    pediatric patients (e.g. ``POP-NNNNN-BABY``), whose stored
    ``PatientProfile`` was initialised at the day of birth with
    newborn values and never advanced as the sim moved forward. For
    the per-encounter FHIR anthropometric Observation emit, use the
    existing growth-chart lookup in
    :mod:`clinosim.modules.population.encounter_anthropometry`
    instead — that path is per-encounter and already age-aware."""
    med = _lookup_median(country, sex, age_years)
    if med is None:
        return None
    h = med["height"]
    w = med["weight"]
    return {
        "height_cm": round(h, 1),
        "weight_kg": round(w, 1),
        "bmi": round(w / ((h / 100) ** 2), 1),
    }
