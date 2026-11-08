"""Issue #2867 — a chronic condition's onset precedes every visit naming it.

The activator used to date every chronic onset 1-14 years before a fixed
2024, while a run can start earlier (e.g. 2021-11). A condition already on
the problem list at the start of the window then got an onset inside the
window, after its first follow-up visit. Onsets are now anchored to the
first simulated year the code is on the list: baseline conditions before
the window, conditions added during the run before the year they are first
followed up.
"""

from __future__ import annotations

from datetime import date

import pytest

from clinosim.locale.loader import load_demographics
from clinosim.modules.patient._patient_activator_thresholds import CHRONIC_ONSET_YEAR_REFERENCE
from clinosim.modules.population.aging import advance_population
from clinosim.modules.population.engine import PopulationRegistry
from clinosim.simulator._setup import _activate_cached_person
from clinosim.types.population import PersonRecord

WINDOW = (date(2021, 11, 9), date(2026, 11, 8))
BASELINE = ["I10", "E78.5", "J44.9", "N18.3"]


def _person(pid: str, codes: list[str]) -> PersonRecord:
    return PersonRecord(
        person_id=pid,
        household_id=f"HH-{pid}",
        age=63,
        sex="M",
        date_of_birth=date(1961, 4, 2),
        chronic_conditions=list(codes),
    )


def _onsets(person: PersonRecord, year: int, cache: dict, seed: int) -> dict[str, date]:
    patient = _activate_cached_person(
        person, as_of_year=year, patient_cache=cache, master_seed=seed, demo=load_demographics("US")
    )
    return {c.code: c.onset_date for c in patient.chronic_conditions}


@pytest.mark.parametrize("seed", range(40))
def test_baseline_onset_precedes_window_start(seed: int) -> None:
    person = _person(f"P-{seed:03d}", BASELINE)
    advance_population(PopulationRegistry(persons={person.person_id: person}), 2021, "US", window=WINDOW)
    onsets = _onsets(person, 2021, {}, seed)
    assert set(onsets) == set(BASELINE)
    for code, onset in onsets.items():
        assert onset < WINDOW[0], f"{code} onset {onset} is inside the window"


def test_incident_onset_precedes_its_first_year() -> None:
    person = _person("P-INC", ["I10"])
    registry = PopulationRegistry(persons={person.person_id: person})
    cache: dict = {}
    advance_population(registry, 2021, "US", window=WINDOW)
    i10_2021 = _onsets(person, 2021, cache, 7)["I10"]
    # Added at the 2025 year boundary (as the longitudinal onset events do).
    person.chronic_conditions.append("E11.9")
    advance_population(registry, 2025, "US", window=WINDOW)
    onsets = _onsets(person, 2025, cache, 7)
    assert date(2024, 1, 1) <= onsets["E11.9"] <= date(2024, 12, 31)
    # The baseline condition keeps its onset across the per-year profiles.
    assert onsets["I10"] == i10_2021


def test_mid_year_addition_dated_before_its_first_profile() -> None:
    person = _person("P-MID", ["I10"])
    registry = PopulationRegistry(persons={person.person_id: person})
    cache: dict = {}
    advance_population(registry, 2021, "US", window=WINDOW)
    advance_population(registry, 2022, "US", window=WINDOW)
    _onsets(person, 2022, cache, 11)
    # Added after the 2022 profile was built (e.g. at a discharge), then first
    # named by a 2023 visit before the 2023 year boundary is processed.
    person.chronic_conditions.append("I48.91")
    onset = _onsets(person, 2023, cache, 11)["I48.91"]
    assert onset <= date(2022, 12, 31)


def test_outside_a_run_keeps_the_fixed_reference() -> None:
    person = _person("P-LEGACY", BASELINE)
    onsets = _onsets(person, 2021, {}, 3)
    assert all(o <= date(CHRONIC_ONSET_YEAR_REFERENCE, 12, 31) for o in onsets.values())
    assert person.chronic_tracked_from is None
