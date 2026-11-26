"""The chronic-onset age floor is a calendar age (Issue #3834).

``12 * 365`` days ignores the leap days between birth and the 12th birthday,
so an onset could land up to three days before it. The floor is the birthday
in calendar years, and every condition the eval lists as adult-only has a
floor at least as high as the eval's pediatric ceiling.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from clinosim.eval.axes import clinical as eval_clinical
from clinosim.locale.loader import load_chronic_age_limits
from clinosim.modules.patient.activator import _clamp_chronic_onset

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("year", range(1996, 2013))
def test_floor_of_12_years_is_the_12th_birthday_across_leap_years(year: int) -> None:
    dob = date(year, 9, 9)
    assert _clamp_chronic_onset(dob + timedelta(days=30), dob, "I10") == date(year + 12, 9, 9)


def test_leap_day_birth_never_floors_before_the_birthday() -> None:
    dob = date(2004, 2, 29)
    floor = _clamp_chronic_onset(dob + timedelta(days=30), dob, "I10")
    assert floor >= date(2016, 2, 28)
    # age in completed years on the floor date is at least 12 by the eval's rule
    assert eval_clinical._age_on(dob, floor) >= 12


def test_sampled_onset_after_the_floor_is_kept() -> None:
    dob = date(2001, 9, 9)
    later = date(2020, 1, 1)
    assert _clamp_chronic_onset(later, dob, "I10") == later


def test_every_adult_only_code_has_a_floor_at_least_the_eval_ceiling() -> None:
    limits = load_chronic_age_limits()
    codes = limits["codes"]
    for code in limits["adult_only_codes"]:
        assert int(codes.get(code, limits["default_min_years"])) >= eval_clinical._PEDIATRIC_AGE_CEILING, code


def _person(age: int, codes: list[str]):  # type: ignore[no-untyped-def]
    from clinosim.types.population import PersonRecord

    return PersonRecord(
        person_id="POP-000321",
        household_id="HH-3",
        age=age,
        sex="M",
        date_of_birth=date(2026 - age, 2, 15),
        family_name="Smith",
        given_name="Alex",
        chronic_conditions=codes,
    )


def test_person_below_the_floor_at_the_anchor_does_not_carry_the_condition() -> None:
    from clinosim.determinism import default_rng
    from clinosim.locale.loader import load_demographics
    from clinosim.modules.patient.activator import activate_patient

    demo = load_demographics("US")
    child = activate_patient(_person(6, ["N18.9", "J45.909"]), default_rng(3), demo)
    codes = {c.code for c in child.chronic_conditions}
    assert "N18.9" not in codes
    assert "J45.909" in codes  # floor 2 years, the child is 6


def test_onset_of_a_floored_condition_is_never_before_the_floor() -> None:
    from clinosim.determinism import default_rng
    from clinosim.locale.loader import load_demographics
    from clinosim.modules.patient.activator import activate_patient

    demo = load_demographics("US")
    for age in (20, 25):
        p = _person(age, ["I10"])
        pt = activate_patient(p, default_rng(5), demo)
        for c in pt.chronic_conditions:
            assert c.onset_date >= p.date_of_birth.replace(year=p.date_of_birth.year + 12)
