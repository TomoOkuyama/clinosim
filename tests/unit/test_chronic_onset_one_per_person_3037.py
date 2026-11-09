"""Issue #3037: a person has one onset date per chronic condition. The
patient profile is re-activated for every simulated year; the first year's
profile can be built before the yearly aging pass has started tracking the
person (``chronic_tracked_from`` unset), and a newborn's conditions are dated
at birth, so a later activation must reuse the onset the person already has
rather than date the condition again."""

from __future__ import annotations

from datetime import date

import numpy as np
import pytest

from clinosim.locale.loader import load_demographics
from clinosim.modules.patient.activator import activate_patient
from clinosim.types.population import PersonRecord

pytestmark = pytest.mark.unit

_DEMO = load_demographics("US")
_DISEASE, _IMPLIED = "acute_mi", "I25"


def _person() -> PersonRecord:
    return PersonRecord(
        person_id="POP-3037",
        household_id="H",
        age=70,
        sex="M",
        date_of_birth=date(1954, 3, 1),
        chronic_conditions=["I10", "E11.9", "N18", "I48"],
    )


def _onsets(person: PersonRecord, year: int) -> dict[str, date]:
    # The simulator seeds every activation of a person with the same stream.
    profile = activate_patient(person, np.random.default_rng(7), _DEMO, as_of_year=year)
    return {c.code: c.onset_date for c in profile.chronic_conditions}


def test_a_profile_built_before_tracking_and_one_after_share_the_onsets() -> None:
    person = _person()
    # First record of the run: the yearly aging pass has not seen the person yet.
    person.note_chronic_conditions(2024)
    first = _onsets(person, 2024)
    # The next year's aging pass starts tracking the person.
    person.chronic_tracked_from = 2025
    person.note_chronic_conditions(2025)
    second = _onsets(person, 2025)
    assert first == second


def test_a_condition_dropped_from_the_list_does_not_move_the_others() -> None:
    # Each code takes its draws in list order, so a code that leaves the list
    # (resolved, or replaced) shifts the draws of every code after it.
    person = _person()
    person.chronic_tracked_from = 2024
    person.note_chronic_conditions(2024)
    first = _onsets(person, 2024)
    person.chronic_conditions.remove("E11.9")
    second = _onsets(person, 2025)
    assert {k: first[k] for k in second} == second


def test_a_newborns_birth_onset_is_kept_by_later_activations() -> None:
    from clinosim.types.patient import ChronicCondition

    baby = PersonRecord(
        person_id="POP-3037-BABY",
        household_id="H",
        age=0,
        sex="F",
        date_of_birth=date(2025, 1, 16),
        chronic_conditions=["L20.9"],
    )
    baby.keep_chronic_onsets([ChronicCondition(code="L20.9", onset_date=date(2025, 1, 16))])
    assert _onsets(baby, 2025)["L20.9"] == date(2025, 1, 16)


def test_an_implied_condition_keeps_its_onset_in_later_stays() -> None:
    """A stay that implies a chronic condition (an acute MI admission ->
    chronic ischaemic heart disease, I25) backdates its onset from the
    admission date; the next year's stay implies it again on that year's
    profile and must reuse it."""
    from datetime import datetime

    from clinosim.simulator.inpatient import _attach_implied_chronic_conditions

    person = _person()
    person.chronic_tracked_from = 2024
    person.note_chronic_conditions(2024)

    def _stay(year: int, when: datetime) -> date:
        profile = activate_patient(person, np.random.default_rng(7), _DEMO, as_of_year=year)
        _attach_implied_chronic_conditions(disease_id=_DISEASE, patient=profile, admission_time=when)
        return {c.code: c.onset_date for c in profile.chronic_conditions}[_IMPLIED]

    assert _stay(2024, datetime(2024, 6, 1, 10)) == _stay(2025, datetime(2025, 1, 15, 10))
