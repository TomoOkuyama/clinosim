"""Pediatric encounter calendar generation (Issue #760 META).

Reads `reference_data/pediatric_schedule.yaml` and, for a given person +
year, emits the pediatric encounters the schedule prescribes for their
age band. Foundation pass ships with an empty schema — the loader
returns `{}` and the generator returns `[]`, so integration into
`generate_healthcare_calendar` is byte-diff neutral.

Determinism notes:
- The generator accepts a caller-supplied `prng` (the per-person
  spawned generator already used by `generate_healthcare_calendar`), so
  no master RNG is consumed here.
- The YAML load is cached via `@lru_cache` per resolved path. Pre-cache,
  the loader was called ~1.3× per patient during the healthcare-calendar
  build (1,325 calls / 19.6s cumulative on a JP p=1000 profile) because
  the schedule ran uncached inside the per-patient generator hot loop.
  Tests that mutate the schedule file can invalidate via
  ``load_pediatric_schedule.cache_clear()``.
"""

from __future__ import annotations

from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from clinosim.age_bands import find_age_band_or_last, parse_age_band
from clinosim.datafiles import load_data_yaml
from clinosim.determinism import sha_bernoulli
from clinosim.modules._shared import random_day_of_month

_YAML_PATH = Path(__file__).parent / "reference_data" / "pediatric_schedule.yaml"

# Vital-sign fields an outpatient visit can measure (``VitalSignRecord``).
VitalField = Literal["temp", "hr", "bp", "rr", "spo2"]


class _Visit(BaseModel):
    """One scheduled pediatric visit type."""

    model_config = ConfigDict(extra="forbid")

    age_min: int = Field(ge=0)
    age_max: int = Field(ge=0)
    visits_per_year: list[int] = Field(min_length=1)
    encounter_type: Literal["outpatient"]
    disease_id: str = Field(min_length=1)
    visit_reason: dict[str, str] | str = ""

    @field_validator("visits_per_year")
    @classmethod
    def _non_negative(cls, counts: list[int]) -> list[int]:
        if any(c < 0 for c in counts):
            raise ValueError("visits_per_year must be non-negative counts")
        return counts

    @field_validator("visit_reason")
    @classmethod
    def _english(cls, reason: dict[str, str] | str) -> dict[str, str] | str:
        if isinstance(reason, dict) and not reason.get("en"):
            raise ValueError("visit_reason needs an English label")
        return reason

    @model_validator(mode="after")
    def _ordered(self) -> _Visit:
        if self.age_min > self.age_max:
            raise ValueError("age_min > age_max")
        return self


class PrescriptionSpec(BaseModel):
    """One take-home prescription item of an acute visit (a short course)."""

    model_config = ConfigDict(extra="forbid")

    drug_id: str = Field(min_length=1)
    dose: str = Field(min_length=1)
    route: str = Field(min_length=1)
    frequency: str = Field(min_length=1)
    # Age band (years) -> course length in days.
    duration_days: dict[str, int] = Field(min_length=1)

    @field_validator("drug_id")
    @classmethod
    def _catalogued(cls, drug_id: str) -> str:
        from clinosim.codes.drugs import get_drug

        if get_drug(drug_id) is None:
            raise ValueError(f"drug {drug_id!r} is not in the drug catalog")
        return drug_id

    @field_validator("duration_days")
    @classmethod
    def _bands(cls, table: dict[str, int]) -> dict[str, int]:
        for band, days in table.items():
            parse_age_band(band)
            if days <= 0:
                raise ValueError(f"duration_days[{band!r}] must be positive")
        return table

    def course_days(self, age: int) -> int:
        """Course length for a child aged ``age`` (the last band when none covers it)."""
        return self.duration_days[find_age_band_or_last(list(self.duration_days), age)]


class Presentation(BaseModel):
    """Clinical picture of an acute pediatric visit (Issue #2873)."""

    model_config = ConfigDict(extra="forbid")

    vitals: list[VitalField] = Field(min_length=1)
    febrile_probability: float = Field(ge=0.0, le=1.0)
    # Visit state ("febrile" / "afebrile") -> state-var deltas.
    state_impact: dict[str, dict[str, float]] = Field(default_factory=dict)
    prescriptions: list[PrescriptionSpec] = Field(default_factory=list)

    @field_validator("state_impact")
    @classmethod
    def _canonical_state_vars(cls, impact: dict[str, dict[str, float]]) -> dict[str, dict[str, float]]:
        from clinosim.modules.physiology.engine import canonical_state_vars

        bad_states = sorted(set(impact) - {"febrile", "afebrile"})
        if bad_states:
            raise ValueError(f"state_impact keys must be febrile / afebrile, got {bad_states}")
        unknown = sorted({var for deltas in impact.values() for var in deltas} - canonical_state_vars())
        if unknown:
            raise ValueError(f"state_impact names non-canonical state vars {unknown}")
        return impact

    @model_validator(mode="after")
    def _febrile_needs_impact(self) -> Presentation:
        if self.febrile_probability > 0 and "febrile" not in self.state_impact:
            raise ValueError("febrile_probability > 0 needs a state_impact.febrile block")
        return self

    def visit_state(self, encounter_id: str) -> Literal["febrile", "afebrile"]:
        """Whether the visit ``encounter_id`` is febrile — a stream-free draw,
        so no simulation RNG stream moves."""
        febrile = sha_bernoulli(f"pediatric-fever|{encounter_id}", self.febrile_probability)
        return "febrile" if febrile else "afebrile"


class _PediatricSchedule(BaseModel):
    """Shape of pediatric_schedule.yaml (validated at load)."""

    model_config = ConfigDict(extra="forbid")

    metadata: dict[str, Any] = Field(default_factory=dict)
    encounters: dict[str, _Visit] = Field(default_factory=dict)
    presentations: dict[str, Presentation] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _presentations_name_visits(self) -> _PediatricSchedule:
        visit_ids = {entry.disease_id for entry in self.encounters.values()}
        unknown = sorted(set(self.presentations) - visit_ids)
        if unknown:
            raise ValueError(f"presentations for unscheduled visits {unknown}")
        return self


@lru_cache(maxsize=8)
def _load_schedule(path: Path = _YAML_PATH) -> _PediatricSchedule:
    raw = load_data_yaml(path) or {}
    try:
        return _PediatricSchedule.model_validate(raw)
    except ValidationError as exc:
        raise ValueError(f"pediatric_schedule.yaml at {path}: {exc}") from exc


@lru_cache(maxsize=8)
def load_pediatric_schedule(path: Path | None = None) -> dict[str, dict[str, Any]]:
    """Load and validate the pediatric encounter schedule.

    Returns a `{encounter_key: entry_dict}` mapping. Empty dict when the
    `encounters:` top-level block is missing or empty (foundation
    default). Raises `ValueError` on schema violations so a malformed
    edit surfaces at load time, not as a mysterious runtime miss.
    """
    config = _load_schedule(path) if path is not None else _load_schedule()
    return {key: entry.model_dump(exclude_none=True) for key, entry in config.encounters.items()}


def pediatric_presentation(visit_id: str) -> Presentation | None:
    """The clinical picture of the acute pediatric visit ``visit_id`` (a
    schedule ``disease_id``), or None for a preventive visit."""
    return _load_schedule().presentations.get(visit_id)


def generate_pediatric_events(
    person: Any,
    year: int,
    prng: np.random.Generator,
    schedule: dict[str, dict[str, Any]] | None = None,
) -> list[Any]:
    """Emit `LifeEvent` records for the pediatric encounters `person` should have this year.

    No-op when the loaded schedule is empty (foundation default) or when
    the person's age falls outside every registered entry's band. `prng`
    is expected to be a per-person spawn'd sub-generator so YAML edits
    do not shift unrelated persons' calendars.
    """
    if schedule is None:
        schedule = load_pediatric_schedule()
    if not schedule:
        return []

    from clinosim.modules.population.engine import LifeEvent

    # Issue #1186 F4: `person.age` is the static age recorded at cohort
    # generation time. When the sim runs multiple years, a 6-year-old
    # recorded at sim start would be 8 by simulation year 2 — but the
    # scheduler previously kept using the static 6, so the pre-
    # kindergarten immunization visit (age_max=6) kept firing for
    # school-age children. Compute the person's actual age at the
    # scheduling year: `year - dob.year` when `date_of_birth` is
    # available; fall back to static `age` otherwise.
    static_age = int(getattr(person, "age", 0) or 0)
    dob = getattr(person, "date_of_birth", None)
    if dob is not None and hasattr(dob, "year"):
        age = int(year) - int(dob.year)
    else:
        age = static_age
    # No pediatric schedule applies for adults; early-return so we don't
    # touch the per-person rng for out-of-band ages (preserves the
    # empty-schedule invariant style for the >18 case).
    if age > 18:
        return []
    # Issue #1564 Phase 1 follow-up: short-circuit for persons not yet
    # born in this cal_year. Newborns registered mid-sim appear in the
    # registry from year 0 of the sim (not from their birth year), and
    # ``generate_healthcare_calendar`` iterates every cal_year in the sim
    # window — without this guard the pediatric calendar would consume
    # one per-person rng draw per pre-birth year on the newborn's own
    # (position-K) stream. The initial cohort's rng streams are not
    # affected because ``spawn(N+K)`` returns the same first N streams as
    # ``spawn(N)``; this guard only avoids RNG waste on the newborn's own
    # stream and prevents a late-year schedule change from drifting the
    # newborn's own pediatric calendar via consumed draws.
    if age < 0:
        return []

    # Issue #922 — care-seeking participation gate.
    #
    # Well-child + immunization visits have severity=0.0, so they bypass
    # the standard `severity > care_seeking_threshold` gate that filters
    # adult acute events. Without a participation gate, EVERY 0-4 child
    # accumulates 5-11 preventive encounters/year and clears any
    # subsequent care-seeking / emit filter, over-representing pediatric
    # patients in the emitted cohort by ~3× vs MHLW 患者調査 2020.
    #
    # The `care_seeking_threshold` on the person represents how motivated
    # the household is to seek/attend care (locale + age-band tuned via
    # ``demographics.yaml``'s ``care_seeking.age_conditional`` — Issue
    # #922). A Bernoulli draw here skips this year's entire pediatric
    # schedule when the parents are less-engaged, dropping pediatric
    # patients out of the emitted cohort proportionally to real MHLW /
    # NAMCS well-child participation attrition (health-literacy gradient
    # + missed-appointment rate). Draws from the per-person spawned rng,
    # not the master RNG.
    threshold = float(getattr(person, "care_seeking_threshold", 0.20) or 0.20)
    if prng.random() < threshold:
        return []

    events: list[Any] = []
    for key, entry in schedule.items():
        if age < int(entry["age_min"]) or age > int(entry["age_max"]):
            continue
        # Uniform sample from the `visits_per_year` list (a list of allowed
        # counts, e.g. [6, 7, 8] for infants — accommodates the AAP well-child
        # schedule's per-year variance rather than a single fixed count).
        n_visits = int(prng.choice(entry["visits_per_year"]))
        if n_visits <= 0:
            continue
        # Space visits evenly across the year with per-visit day jitter.
        for i in range(n_visits):
            month = min(12, max(1, int((12 * (i + 0.5)) / max(1, n_visits))))
            day = random_day_of_month(prng, year, month)
            events.append(
                LifeEvent(
                    person_id=person.person_id,
                    event_type="pediatric_visit",
                    timestamp=date(year, month, day),
                    severity=0.0,
                    condition_type="pediatric",
                    disease_id=entry["disease_id"],
                    encounter_type=entry.get("encounter_type", "outpatient"),
                    protocol_source=f"pediatric:{key}",
                )
            )
    return events
