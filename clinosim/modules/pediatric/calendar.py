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
- The YAML is parsed once at call time (small file); no lru_cache to
  keep hot-reload friendly for tests. Callers who care about repeat
  cost can cache the result of `load_pediatric_schedule()`.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import yaml

_YAML_PATH = Path(__file__).parent / "reference_data" / "pediatric_schedule.yaml"


def load_pediatric_schedule(path: Path | None = None) -> dict[str, dict[str, Any]]:
    """Load and validate the pediatric encounter schedule.

    Returns a `{encounter_key: entry_dict}` mapping. Empty dict when the
    `encounters:` top-level block is missing or empty (foundation
    default). Raises `ValueError` on schema violations so a malformed
    edit surfaces at load time, not as a mysterious runtime miss.
    """
    p = path or _YAML_PATH
    with p.open(encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    encounters = raw.get("encounters") or {}
    if not isinstance(encounters, dict):
        raise ValueError(f"pediatric_schedule.yaml at {p}: top-level 'encounters' must be a mapping")
    for key, entry in encounters.items():
        if not isinstance(entry, dict):
            raise ValueError(f"pediatric_schedule.yaml: encounter '{key}' entry must be a dict")
        for required in ("age_min", "age_max", "visits_per_year", "encounter_type", "disease_id"):
            if required not in entry:
                raise ValueError(f"pediatric_schedule.yaml: encounter '{key}' missing required '{required}'")
        if not isinstance(entry["visits_per_year"], list) or not entry["visits_per_year"]:
            raise ValueError(f"pediatric_schedule.yaml: encounter '{key}' 'visits_per_year' must be a non-empty list")
        if int(entry["age_min"]) > int(entry["age_max"]):
            raise ValueError(f"pediatric_schedule.yaml: encounter '{key}' age_min > age_max")
    return encounters


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

    age = int(getattr(person, "age", 0) or 0)
    # No pediatric schedule applies for adults; early-return so we don't
    # touch the per-person rng for out-of-band ages (preserves the
    # empty-schedule invariant style for the >18 case).
    if age > 18:
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
            day = int(prng.integers(1, 28))
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
