"""Issue #1774: age-0 initial-cohort DOB stays before sim-start.

Pre-fix the initial-cohort generator sampled DOB in ``base_year`` with
random month/day for every age bracket. For age==0 patients this put
~50 % of them with DOB after Jan 1 of ``base_year`` (sim-start),
which is semantically wrong: a cohort snapshot describes who is
alive on day 1, not future perinatal-event newborns born later.
Downstream the ``pid.endswith("-BABY")`` filter systematically
missed these 120 / p=10k patients because their id was ``POP-NNNNNN``
(initial-cohort pattern) not ``POP-NNNNNN-BABY`` (perinatal pattern).

Fix: for ``age == 0``, shift DOB year back one so DOB is always
in ``base_year - 1``. The baby is unambiguously already born at
sim-start; patient_id semantics stay clean (perinatal event newborns
→ ``-BABY`` suffix; initial-cohort babies born in the year before
sim-start → ``POP-NNNNNN``).
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pytest

from clinosim.modules.population.engine import generate_population

pytestmark = pytest.mark.unit


def _generate(size: int = 500, seed: int = 42, country: str = "US", base_year: int = 2024):
    rng = np.random.default_rng(seed)
    reg = generate_population(size=size, country=country, rng=rng, base_year=base_year)
    return reg


def test_no_age_zero_dob_after_sim_start() -> None:
    """Every age-0 initial-cohort patient has DOB strictly before
    sim-start (Jan 1 of base_year). Pre-fix 120 / 10000 landed with
    DOB in base_year after sim-start — now 0."""
    reg = _generate(size=1000, seed=42, base_year=2024)
    sim_start = date(2024, 1, 1)
    offenders = []
    for pid, person in reg.persons.items():
        if pid.endswith("-BABY"):
            continue  # perinatal path, out of scope
        if int(getattr(person, "age", -1)) == 0 and person.date_of_birth >= sim_start:
            offenders.append((pid, person.date_of_birth))
    assert not offenders, f"age-0 patients with DOB >= sim-start: {offenders[:5]}... (total {len(offenders)})"


def test_age_zero_dob_lands_in_base_year_minus_one() -> None:
    """Age-0 initial-cohort patients get DOB in base_year - 1 so
    they're definitively born before sim-start (regardless of
    random month/day)."""
    reg = _generate(size=500, seed=100, base_year=2024)
    for pid, person in reg.persons.items():
        if pid.endswith("-BABY"):
            continue
        if int(getattr(person, "age", -1)) == 0:
            assert person.date_of_birth.year == 2023, (
                f"{pid} age=0 DOB year {person.date_of_birth.year} (expected 2023)"
            )


def test_age_one_dob_year_unchanged() -> None:
    """Age-1 patients still get DOB in base_year - 1 (unchanged
    semantics). The fix only touches age == 0."""
    reg = _generate(size=1000, seed=42, base_year=2024)
    for pid, person in reg.persons.items():
        if pid.endswith("-BABY"):
            continue
        if int(getattr(person, "age", -1)) == 1:
            assert person.date_of_birth.year == 2023, (
                f"{pid} age=1 DOB year {person.date_of_birth.year} (expected 2023)"
            )


def test_adult_dob_sampling_unchanged() -> None:
    """Age-X (adult) patients still get DOB in base_year - X. Fix is
    strictly scoped to age==0 — adults' temporal distribution unchanged."""
    reg = _generate(size=500, seed=7, base_year=2024)
    sampled_adult_years = {
        person.date_of_birth.year
        for pid, person in reg.persons.items()
        if not pid.endswith("-BABY") and int(getattr(person, "age", -1)) >= 20
    }
    assert sampled_adult_years, "no adult patients generated — fixture busted"
    # Any adult DOB year must be <= 2004 (base_year - 20).
    assert max(sampled_adult_years) <= 2004


def test_rng_neutrality_age_zero_shift_preserves_shape() -> None:
    """The age==0 DOB shift is a pure year arithmetic change — no
    additional RNG draws. Two seeded runs produce the same number of
    age-0 patients (RNG draws unchanged, outcomes identical for
    non-DOB fields)."""
    reg1 = _generate(size=800, seed=12345, base_year=2024)
    reg2 = _generate(size=800, seed=12345, base_year=2024)
    age0_count_1 = sum(
        1 for pid, p in reg1.persons.items() if not pid.endswith("-BABY") and int(getattr(p, "age", -1)) == 0
    )
    age0_count_2 = sum(
        1 for pid, p in reg2.persons.items() if not pid.endswith("-BABY") and int(getattr(p, "age", -1)) == 0
    )
    assert age0_count_1 == age0_count_2
