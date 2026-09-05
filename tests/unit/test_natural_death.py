"""Natural-death sampling enricher tests (Issue #1114 C11g-2).

Covers:
  - ``PersonRecord.is_alive_at(t)`` correctness (None death → always alive;
    death present → strictly-before predicate).
  - Enricher deterministic under the same master seed.
  - Cohort mortality rate lands in the CDC/MHLW real-world band
    (7-13 /kyr) for a moderately-sized synthetic population.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from types import SimpleNamespace

import pytest

from clinosim.modules.natural_death import sample_natural_deaths
from clinosim.types.population import PersonRecord


@pytest.mark.unit
class TestIsAliveAt:
    def _person(self, dod: date | None) -> PersonRecord:
        return PersonRecord(
            person_id="p1",
            household_id="h1",
            age=40,
            sex="M",
            date_of_birth=date(1985, 6, 15),
            date_of_death=dod,
        )

    def test_no_death_is_always_alive(self):
        p = self._person(None)
        assert p.is_alive_at(date(1900, 1, 1)) is True
        assert p.is_alive_at(date(2050, 12, 31)) is True

    def test_alive_strictly_before_death(self):
        p = self._person(date(2025, 6, 15))
        assert p.is_alive_at(date(2025, 6, 14)) is True

    def test_dead_on_death_date(self):
        p = self._person(date(2025, 6, 15))
        # Day-of-death: person is considered not-alive (matches actuarial convention).
        assert p.is_alive_at(date(2025, 6, 15)) is False

    def test_dead_after_death_date(self):
        p = self._person(date(2025, 6, 15))
        assert p.is_alive_at(date(2025, 6, 16)) is False
        assert p.is_alive_at(date(2030, 1, 1)) is False


@dataclass
class _FakePopulation:
    persons: dict


def _make_cohort(n_per_age_band: int = 100) -> _FakePopulation:
    """Build a synthetic cohort across all age bands with sex balance."""
    persons: dict = {}
    idx = 0
    for age_band_lo in range(0, 100, 5):
        for offset in range(5):  # 5 ages per band
            age = age_band_lo + offset
            for sex in ("M", "F"):
                for _ in range(max(1, n_per_age_band // 20)):  # size per band
                    pid = f"p{idx:05d}"
                    persons[pid] = PersonRecord(
                        person_id=pid,
                        household_id=f"h{idx:05d}",
                        age=age,
                        sex=sex,
                        date_of_birth=date(2020 - age, 6, 15),
                    )
                    idx += 1
    return _FakePopulation(persons=persons)


def _make_ctx(country: str, seed: int, cohort: _FakePopulation, years: int = 5) -> SimpleNamespace:
    start = "2023-01-01"
    end = f"{2022 + years}-12-31"
    return SimpleNamespace(
        config=SimpleNamespace(country=country, time_range=(start, end)),
        master_seed=seed,
        population=cohort,
    )


@pytest.mark.unit
class TestSampleNaturalDeaths:
    def test_deterministic_across_seeds(self):
        cohort_a = _make_cohort()
        cohort_b = _make_cohort()
        sample_natural_deaths(_make_ctx("US", 42, cohort_a))
        sample_natural_deaths(_make_ctx("US", 42, cohort_b))
        deaths_a = [p.date_of_death for p in cohort_a.persons.values()]
        deaths_b = [p.date_of_death for p in cohort_b.persons.values()]
        assert deaths_a == deaths_b, "Same seed must produce identical death dates"

    def test_us_cohort_mortality_in_realistic_band(self):
        cohort = _make_cohort()
        sample_natural_deaths(_make_ctx("US", 322, cohort, years=5))
        n_total = len(cohort.persons)
        n_dead = sum(1 for p in cohort.persons.values() if p.date_of_death is not None)
        per_kyr = n_dead / n_total * 1000 / 5
        # US CDC 2020 all-cause mortality is ~8.7 /kyr against the
        # actual US age distribution, but this test's uniform-per-age
        # cohort (5 persons at each age 0-99) integrates over the very-
        # old tail (85+ qx > 0.1) at 20 × the real weight, so raw
        # observed rate lands ~2-3× higher. Widened to 8-40 /kyr —
        # narrow enough to catch a broken sampler (0/kyr) or a wildly
        # inflated one, wide enough to accept the cohort-shape effect.
        assert 8.0 <= per_kyr <= 40.0, f"US cohort mortality {per_kyr:.2f}/kyr outside realistic band"

    def test_jp_cohort_mortality_in_realistic_band(self):
        cohort = _make_cohort()
        sample_natural_deaths(_make_ctx("JP", 321, cohort, years=5))
        n_total = len(cohort.persons)
        n_dead = sum(1 for p in cohort.persons.values() if p.date_of_death is not None)
        per_kyr = n_dead / n_total * 1000 / 5
        # JP MHLW 2020 all-cause mortality is ~11.4 /kyr against the
        # actual JP age distribution; same uniform-cohort widening as
        # the US test.
        assert 8.0 <= per_kyr <= 40.0, f"JP cohort mortality {per_kyr:.2f}/kyr outside realistic band"

    def test_death_date_within_sim_window(self):
        cohort = _make_cohort()
        sample_natural_deaths(_make_ctx("US", 100, cohort, years=5))
        start, end = date(2023, 1, 1), date(2027, 12, 31)
        for person in cohort.persons.values():
            if person.date_of_death is not None:
                assert start <= person.date_of_death <= end, (
                    f"Death {person.date_of_death} for {person.person_id} outside sim window"
                )

    def test_elderly_more_likely_to_die_than_young(self):
        """Sanity: age monotonicity in aggregate. Grouping the cohort by
        age band 0-19 vs 80+, the elderly band should have a much higher
        death rate. Catches accidental age-lookup swaps in ``_qx_for``."""
        cohort = _make_cohort(n_per_age_band=200)
        sample_natural_deaths(_make_ctx("US", 500, cohort, years=5))
        young_dead = sum(1 for p in cohort.persons.values() if p.age < 20 and p.date_of_death is not None)
        young_total = sum(1 for p in cohort.persons.values() if p.age < 20)
        old_dead = sum(1 for p in cohort.persons.values() if p.age >= 80 and p.date_of_death is not None)
        old_total = sum(1 for p in cohort.persons.values() if p.age >= 80)
        young_rate = young_dead / max(1, young_total)
        old_rate = old_dead / max(1, old_total)
        assert old_rate > 5 * young_rate, f"Elderly mortality {old_rate:.4f} should be >5x young {young_rate:.4f}"
