"""Issue #957 Tier-3-A — chemotherapy cycle scheduling.

Guards the population healthcare-calendar generator's ``chemo_visit``
event emission for chronic-cancer carriers whose per-patient deterministic
sub-RNG assigns them an active chemo regimen from
``chemo_regimens.yaml``. Slice-1 scope: Encounter + Procedure emit at
the correct cycle cadence (no per-cycle drug MedicationAdministration
yet — that's a follow-up slice).

Determinism contract (RNG-shape neutrality):
    ``_chemo_cycle_events`` MUST consume zero calls on the calendar's
    shared per-person ``prng``; every random draw uses
    ``chemotherapy_regimen_seed(person_id, cancer_code)``. Adding this
    scheduler MUST NOT shift any pre-existing calendar event stream.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pytest

from clinosim.modules.population.engine import (
    PopulationRegistry,
    _chemo_cycle_events,
    generate_healthcare_calendar,
)
from clinosim.types.population import LifeEvent, PersonRecord

pytestmark = pytest.mark.unit


def _make_person(pid: str, sex: str, age: int, chronic_codes: list[str]) -> PersonRecord:
    """Minimal PersonRecord: only the fields _chemo_cycle_events reads
    (person_id, chronic_conditions). All physiology / lifestyle fields
    default; is_alive defaults to True."""
    return PersonRecord(
        person_id=pid,
        household_id="HH-000001",
        age=age,
        sex=sex,
        date_of_birth=date(2026 - age, 1, 1),
        chronic_conditions=list(chronic_codes),
    )


# ---------------------------------------------------------------------------
# _chemo_cycle_events — regimen selection + cycle date math
# ---------------------------------------------------------------------------


def test_no_cancer_conditions_emits_no_chemo_events() -> None:
    """A patient without any cancer chronic code produces zero chemo_visit
    events (baseline: non-cancer patients are untouched)."""
    person = _make_person("POP-000001", "F", 65, ["I10", "E11.9"])  # HTN + DM only
    assert _chemo_cycle_events(person, year=2024) == []


def test_cancer_code_without_by_cancer_entry_emits_nothing() -> None:
    """A cancer code that has NO entry in ``by_cancer`` (e.g. C22 liver,
    C15 esophageal — surveillance-only in slice 1) produces zero events
    even when the patient carries the code."""
    for code in ("C22", "C15", "C16", "C25", "C67", "C71"):
        person = _make_person(f"POP-{code}", "F", 60, [code])
        events = _chemo_cycle_events(person, year=2024)
        assert events == [], f"code {code} should not emit chemo events in slice 1, got {events}"


def test_cancer_code_with_regimen_emits_events_at_cycle_cadence() -> None:
    """A patient whose sub-RNG assigns an active regimen must produce
    chemo_visit events spaced at the regimen's ``cycle_interval_days``."""
    # POP-000042 with C61 (LHRH_q28d, probability=0.35) — with enough patients
    # the assignment WILL fire for at least one. We sweep patient ids to find
    # one whose sub-RNG picks the regimen.
    for i in range(200):
        pid = f"POP-{i:06d}"
        person = _make_person(pid, "M", 72, ["C61"])
        events = _chemo_cycle_events(person, year=2024)
        if events:
            # All events must be chemo_visit tagged for this cancer + regimen
            assert all(e.event_type == "chemo_visit" for e in events), events
            assert all(e.disease_id == "C61" for e in events), events
            assert all(e.protocol_source == "chemo_regimens:LHRH_q28d" for e in events), events
            # Cycle spacing must be exactly 28 days
            dates = sorted(e.timestamp for e in events)
            gaps = [(dates[i + 1] - dates[i]).days for i in range(len(dates) - 1)]
            assert all(g == 28 for g in gaps), f"non-28-day gaps for {pid}: {gaps}"
            # Course_cycles=24 caps below 365/28=13.04 — annual cap wins
            assert len(events) <= 13, f"{pid} exceeded annual cycle cap: {len(events)}"
            return
    pytest.fail("No C61 patient picked LHRH_q28d across 200 sub-RNG draws — check probability")


def test_folfox_c18_cycle_interval_is_14_days() -> None:
    """FOLFOX regimen for C18 must space cycles 14 days apart."""
    for i in range(200):
        pid = f"POP-{i:06d}"
        person = _make_person(pid, "F", 65, ["C18"])
        events = _chemo_cycle_events(person, year=2024)
        if events and events[0].protocol_source == "chemo_regimens:FOLFOX":
            dates = sorted(e.timestamp for e in events)
            gaps = [(dates[i + 1] - dates[i]).days for i in range(len(dates) - 1)]
            assert all(g == 14 for g in gaps), f"non-14-day gaps: {gaps}"
            # course_cycles=12 caps the year
            assert len(events) <= 12
            return
    pytest.fail("No C18 patient picked FOLFOX across 200 draws")


def test_regimen_selection_is_deterministic_per_patient() -> None:
    """Same person_id + cancer_code always selects the same regimen
    (RNG-neutral: no dependency on when the scheduler runs)."""
    person = _make_person("POP-000042", "M", 72, ["C61"])
    events_a = _chemo_cycle_events(person, year=2024)
    events_b = _chemo_cycle_events(person, year=2024)
    assert len(events_a) == len(events_b)
    for a, b in zip(events_a, events_b):
        assert a.timestamp == b.timestamp
        assert a.protocol_source == b.protocol_source


def test_regimen_selection_stable_across_years() -> None:
    """Same patient in 2024 vs 2025 gets identical regimen assignment
    (year affects only the timestamps, not whether/which regimen fires)."""
    person = _make_person("POP-000042", "M", 72, ["C61"])
    events_2024 = _chemo_cycle_events(person, year=2024)
    events_2025 = _chemo_cycle_events(person, year=2025)
    # Either both fire (with same regimen) or both are empty.
    assert bool(events_2024) == bool(events_2025)
    if events_2024:
        assert events_2024[0].protocol_source == events_2025[0].protocol_source


# ---------------------------------------------------------------------------
# generate_healthcare_calendar — end-to-end RNG-neutrality contract
# ---------------------------------------------------------------------------


def _seed_registry(persons: list[PersonRecord]) -> PopulationRegistry:
    reg = PopulationRegistry()
    for p in persons:
        reg.persons[p.person_id] = p
    return reg


def test_chemo_scheduler_does_not_shift_non_chemo_calendar_stream() -> None:
    """RNG-neutrality regression: calendar events for non-cancer patients
    (and non-chemo events for cancer patients) must be byte-identical
    whether or not the ``_chemo_cycle_events`` block runs.

    Strategy: generate the calendar twice, once with an all-non-cancer
    population and once with a mixed population. The non-cancer patient
    slice's events must match position-by-position between the two runs.
    """
    non_cancer = [_make_person(f"POP-N{i:04d}", "F", 60, ["I10"]) for i in range(20)]
    cancer_slice = [_make_person(f"POP-C{i:04d}", "M", 72, ["C61"]) for i in range(20)]

    reg_a = _seed_registry(non_cancer)
    reg_b = _seed_registry(non_cancer + cancer_slice)

    events_a = generate_healthcare_calendar(reg_a, year=2024, country="JP", rng=np.random.default_rng(42))
    events_b = generate_healthcare_calendar(reg_b, year=2024, country="JP", rng=np.random.default_rng(42))

    def by_person(evs: list[LifeEvent], pid_prefix: str) -> list[tuple[str, date, str, str]]:
        return sorted(
            (e.person_id, e.timestamp, e.event_type, e.disease_id) for e in evs if e.person_id.startswith(pid_prefix)
        )

    non_cancer_a = by_person(events_a, "POP-N")
    non_cancer_b = by_person(events_b, "POP-N")
    assert non_cancer_a == non_cancer_b, (
        f"Adding cancer patients shifted non-cancer patients' calendar streams: "
        f"len_a={len(non_cancer_a)} len_b={len(non_cancer_b)}"
    )


def test_chemo_events_actually_emit_in_healthcare_calendar() -> None:
    """Positive baseline: a population of C61 chronic carriers must
    produce SOME chemo_visit events via ``generate_healthcare_calendar``
    (the top-level entry point) — proves the scheduler is wired in."""
    cohort = [_make_person(f"POP-{i:06d}", "M", 72, ["C61"]) for i in range(50)]
    reg = _seed_registry(cohort)
    events = generate_healthcare_calendar(reg, year=2024, country="JP", rng=np.random.default_rng(42))
    chemo = [e for e in events if e.event_type == "chemo_visit"]
    assert chemo, "healthcare calendar produced zero chemo_visit events for a C61-heavy cohort"
    # Every chemo event must reference a valid regimen and a chemo_infusion condition_type
    for e in chemo:
        assert e.condition_type == "chemo_infusion", e
        assert e.protocol_source.startswith("chemo_regimens:"), e
        assert e.encounter_type == "outpatient", e
