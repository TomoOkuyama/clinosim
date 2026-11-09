"""Issue #3006: JP pediatric series doses keep the 定期接種実施要領 intervals.

Hib / PCV13 / 四種混合 primary doses are at least 27 / 27 / 20 days apart
(the JP dose windows touch, 91-120 days right after 60-90), Japanese
encephalitis 1期初回 doses 1 and 2 are 6-28 days apart with the 追加 dose
about a year later and 2期 at 9-12 years, and a vaccination visit does not
give a dose sooner than the series allows.
"""

from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace

import numpy as np
import pytest

from clinosim.modules.immunization.engine import (
    dose_intervals_by_cvx,
    generate_immunizations,
    load_schedule,
    series_allows,
)
from clinosim.modules.immunization.visits import VaccinationVisit, bind_to_vaccination_visits
from clinosim.types.encounter import ImmunizationRecord

pytestmark = pytest.mark.unit

_JP = load_schedule("JP")
_RULES = dose_intervals_by_cvx(_JP)


def _child(dob: date, pid: str = "P1") -> SimpleNamespace:
    return SimpleNamespace(patient_id=pid, date_of_birth=dob, age=(date(2026, 11, 1) - dob).days // 365, sex="F")


def _doses(dob: date, seed: int, as_of: date = date(2026, 11, 1)) -> dict[str, dict[int, date]]:
    out: dict[str, dict[int, date]] = {}
    for imm in generate_immunizations(_child(dob, f"P{seed}"), _JP, as_of, np.random.default_rng(seed)):
        if imm.status == "completed" and imm.dose_number:
            out.setdefault(imm.vaccine_cvx, {})[imm.dose_number] = imm.occurrence_date
    return out


@pytest.mark.parametrize("seed", range(30))
def test_hib_dose_3_is_at_least_27_days_after_dose_2(seed: int) -> None:
    doses = _doses(date(2024, 1, 1) + timedelta(days=seed * 7), seed)
    hib = doses.get("17", {})
    if 2 in hib and 3 in hib:
        assert (hib[3] - hib[2]).days >= 27


@pytest.mark.parametrize("seed", range(30))
def test_every_jp_series_keeps_its_intervals(seed: int) -> None:
    for cvx, doses in _doses(date(2013, 1, 1) + timedelta(days=seed * 61), seed).items():
        for number, rule in (_RULES.get(cvx) or {}).items():
            if number in doses and rule.after_dose in doses:
                gap = (doses[number] - doses[rule.after_dose]).days
                assert gap >= rule.min_days, (cvx, number, gap)
                assert rule.max_days is None or gap <= rule.max_days, (cvx, number, gap)


@pytest.mark.parametrize("seed", range(30))
def test_je_doses_1_and_2_are_6_to_28_days_apart(seed: int) -> None:
    dob = date(2016, 1, 1) + timedelta(days=seed * 23)
    je = _doses(dob, seed).get("129", {})
    if 1 in je and 2 in je:  # dose 2 is given to most (coverage 0.88)
        assert 6 <= (je[2] - je[1]).days <= 28
    if 3 in je:
        assert 300 <= (je[3] - je[2]).days <= 450  # 追加: about a year later
    if 4 in je:
        assert 9 <= (je[4] - dob).days / 365.25 < 13  # 2期: 9-12 years


def test_series_allows_keeps_the_maximum_interval() -> None:
    d1 = ImmunizationRecord(vaccine_cvx="129", occurrence_date=date(2020, 1, 10), dose_number=1)
    d2 = ImmunizationRecord(vaccine_cvx="129", occurrence_date=date(2020, 1, 30), dose_number=2)
    rules = _RULES["129"]
    assert series_allows(d2, date(2020, 1, 30), [d1, d2], rules)
    assert not series_allows(d2, date(2020, 1, 13), [d1, d2], rules)  # 3 days < 6
    assert not series_allows(d2, date(2020, 3, 1), [d1, d2], rules)  # 51 days > 28


def test_a_vaccination_visit_does_not_give_a_dose_too_soon() -> None:
    """Hib dose 1 at day 88 (2 months); a visit at day 100 is inside dose 2's
    age window (91-120 days) but only 12 days later: no dose 2 there."""
    dob = date(2025, 1, 1)
    d1 = ImmunizationRecord(vaccine_cvx="17", occurrence_date=dob + timedelta(days=88), dose_number=1)
    d1.encounter_id = "ENC-V1"
    visit = VaccinationVisit(encounter_id="ENC-V2", day=dob + timedelta(days=100), is_flu=False)
    hib_only = {k: v for k, v in _JP.items() if k == "pediatric_hib"}
    out = bind_to_vaccination_visits(
        [d1], [visit], _child(dob), hib_only, as_of=date(2026, 11, 1), sim_start=None, flu_visit_candidate=False
    )
    given = [i for i in out if i.status == "completed" and i.encounter_id == "ENC-V2"]
    assert given == [], given
