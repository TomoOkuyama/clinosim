"""Last known well of an acute stroke admission (Issue #3558).

``last_known_well`` is the arrival at the hospital minus an onset-to-arrival
interval drawn from a hash of the encounter id (:func:`sha_lognormal`), so no
simulation RNG stream is consumed. The distribution (per country) is
``reference_data/stroke_onset_to_arrival.yaml``. The simulator does not model
thrombolysis, so no treatment decision depends on the interval.
"""

from __future__ import annotations

import functools
from datetime import datetime, timedelta
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator

from clinosim.datafiles import load_validated_yaml
from clinosim.determinism import sha_lognormal


class _Interval(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    median_minutes: float = Field(gt=0)
    sigma: float = Field(ge=0)


class StrokeOnsetRules(BaseModel):
    """Schema of ``reference_data/stroke_onset_to_arrival.yaml``."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    disease_ids: tuple[str, ...] = Field(min_length=1)
    min_minutes: float = Field(gt=0)
    max_minutes: float = Field(gt=0)
    default: str
    countries: dict[str, _Interval] = Field(min_length=1)

    @model_validator(mode="after")
    def _consistent(self) -> StrokeOnsetRules:
        if self.min_minutes >= self.max_minutes:
            raise ValueError("stroke_onset_to_arrival.yaml: min_minutes must be below max_minutes")
        if self.default not in self.countries:
            raise ValueError("stroke_onset_to_arrival.yaml: default must name an entry of countries")
        return self


@functools.cache
def stroke_onset_rules() -> StrokeOnsetRules:
    """The validated onset-to-arrival rules."""
    path = Path(__file__).resolve().parent / "reference_data" / "stroke_onset_to_arrival.yaml"
    return StrokeOnsetRules.model_validate(load_validated_yaml(path, StrokeOnsetRules))


def last_known_well(encounter_id: str, disease_id: str, arrival: datetime, country: str) -> datetime | None:
    """The last-known-well time of an acute stroke admission arriving at
    ``arrival``; ``None`` for a disease that is not an acute stroke. ``country`` is the
    disease-YAML country key (``"us"`` / ``"japan"``)."""
    rules = stroke_onset_rules()
    if disease_id not in rules.disease_ids:
        return None
    interval = rules.countries.get(country.lower()) or rules.countries[rules.default]
    minutes = sha_lognormal(f"{encounter_id}|last_known_well", interval.median_minutes, interval.sigma)
    minutes = min(max(minutes, rules.min_minutes), rules.max_minutes)
    return arrival - timedelta(minutes=round(minutes))
