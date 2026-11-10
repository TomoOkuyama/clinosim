"""Country parameters moved from Python constants to locale YAML (Issue #3142).

``docs/design-guides/country-profile-spec.md`` §3.2 / §7 step 3: values that
differ by country live in ``clinosim/locale/<cc>/<topic>.yaml`` and are read
through a loader. Each file is validated by a Pydantic model
(``extra="forbid"``, frozen). The country is resolved through the country
profile, so an unknown country raises ``KeyError`` instead of falling back to
another country's values.

- ``care_practice.yaml`` — :class:`CarePractice`: discharge criteria, time to
  surgery, inpatient rehab session length.
- ``population_genetics.yaml`` — :class:`PopulationGenetics`: RhD-positive
  fraction, ABO allele frequencies, drug-metabolizer phenotypes.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import BaseModel, ConfigDict, Field

from clinosim.country_profile import country_profile
from clinosim.locale._io import _country_dir, _load_yaml

__all__ = [
    "CarePractice",
    "DischargeCriteria",
    "PopulationGenetics",
    "TimeToSurgery",
    "load_care_practice",
    "load_population_genetics",
]


class _Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class DischargeCriteria(_Frozen):
    """State thresholds a patient must meet to be discharged (all strict)."""

    inflammation_max: float
    perfusion_min: float
    renal_min: float
    volume_abs_max: float
    ph_abs_max: float


class TimeToSurgery(_Frozen):
    """Hours from admission to incision: ``max(floor, normal(mean, sd))``."""

    mean: float
    sd: float = Field(ge=0)
    floor: float = Field(ge=0)


class CarePractice(_Frozen):
    """``locale/<cc>/care_practice.yaml``."""

    discharge_criteria: DischargeCriteria
    time_to_surgery_hours: TimeToSurgery
    rehab_session_minutes: int = Field(gt=0)


class PopulationGenetics(_Frozen):
    """``locale/<cc>/population_genetics.yaml``."""

    rh_positive_fraction: float = Field(ge=0, le=1)
    abo_allele_frequencies: dict[str, float]
    # Phenotype -> probability, in draw order.
    drug_metabolism_phenotypes: dict[str, float]


def _country_file(country: str, name: str) -> dict:
    code = country_profile(country).code  # KeyError for an unknown country
    data = _load_yaml(_country_dir(code) / name, fallback=None)
    if not isinstance(data, dict) or not data:
        raise FileNotFoundError(f"locale/{code.lower()}/{name} is missing or empty")
    return data


@lru_cache(maxsize=8)
def load_care_practice(country: str) -> CarePractice:
    """The country's inpatient care-practice parameters."""
    return CarePractice.model_validate(_country_file(country, "care_practice.yaml"))


@lru_cache(maxsize=8)
def load_population_genetics(country: str) -> PopulationGenetics:
    """The country's population-genetics parameters."""
    return PopulationGenetics.model_validate(_country_file(country, "population_genetics.yaml"))
