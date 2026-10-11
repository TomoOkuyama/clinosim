"""Phase 2: `advance_population` aging hook — Issue #1564.

Covers:

* Scaffold invariants (seed isolation, dead-skip, locale wiring).
* ``_annual_chronic_onset`` behaviour: age gate, sex gate,
  already-present skip, deterministic draws, band-diff derivation
  math, approximate marginal preservation across a decade.
* Stub signatures for the three not-yet-implemented passes.
"""

from __future__ import annotations

from datetime import date

import numpy as np

from clinosim.modules.population.aging import (
    _allergy_drift,
    _annual_chronic_onset,
    _condition_reactive_mortality,
    _derive_annual_incidence_from_prevalence,
    _disease_progression,
    _load_annual_incidence_for_locale,
    advance_population,
    aging_sub_seed,
)
from clinosim.modules.population.engine import PopulationRegistry
from clinosim.types.population import PersonRecord


def _alive(pid: str, age: int = 50, sex: str = "M") -> PersonRecord:
    return PersonRecord(
        person_id=pid,
        household_id="HH-1",
        age=age,
        sex=sex,
        date_of_birth=date(2026 - age, 1, 1),
    )


def _registry(persons: list[PersonRecord]) -> PopulationRegistry:
    reg = PopulationRegistry()
    for p in persons:
        reg.persons[p.person_id] = p
    reg.initial_person_ids = set(reg.persons.keys())
    return reg


# ---------------------------------------------------------------------------
# Scaffold invariants
# ---------------------------------------------------------------------------


def test_aging_sub_seed_deterministic_and_pass_isolated() -> None:
    s1 = aging_sub_seed("PT-1", 2026, "chronic_onset")
    s2 = aging_sub_seed("PT-1", 2026, "chronic_onset")
    assert s1 == s2
    assert s1 != aging_sub_seed("PT-1", 2026, "disease_progression")
    assert s1 != aging_sub_seed("PT-1", 2027, "chronic_onset")
    assert s1 != aging_sub_seed("PT-2", 2026, "chronic_onset")


def test_advance_population_skips_dead_persons() -> None:
    p_dead = _alive("PT-DEAD", age=90)
    p_dead.is_alive = False
    p_dead_before = list(p_dead.chronic_conditions)
    p_alive = _alive("PT-ALIVE", age=50)
    reg = _registry([p_dead, p_alive])
    advance_population(reg, 2026, "us")
    # Dead person untouched.
    assert p_dead.chronic_conditions == p_dead_before
    assert p_dead.is_alive is False
    assert p_alive.is_alive is True


def test_pass_stubs_are_callable_no_op() -> None:
    """Three Phase-2 stub passes still accept ``(person, year, prng,
    incidence_table)`` and return ``None`` without touching state."""
    p = _alive("PT-X", age=65)
    before = (tuple(p.chronic_conditions), p.is_alive, p.date_of_death)
    for fn in (_disease_progression, _allergy_drift, _condition_reactive_mortality):
        rv = fn(p, 2026, np.random.default_rng(42), {})
        assert rv is None
    after = (tuple(p.chronic_conditions), p.is_alive, p.date_of_death)
    assert before == after


# ---------------------------------------------------------------------------
# Band-diff derivation math
# ---------------------------------------------------------------------------


def test_derive_last_band_rate_is_zero() -> None:
    """Highest band has no next prevalence to climb toward, so λ=0."""
    out = _derive_annual_incidence_from_prevalence({(40, 59): 0.30, (60, 79): 0.50})
    assert out[(60, 79)] == 0.0


def test_derive_band_diff_recovers_prev_next() -> None:
    """A susceptible person aged across the full width of band
    ``[40, 59]`` should end at prevalence close to ``P_next``.

    Formula: (1 - λ)^width = (1 - P_next) / (1 - P_this)
    Width 20, P_this 0.30, P_next 0.50 → λ ≈ 0.01676.
    Cumulative onset over 20 years = 1 - (1 - 0.01676)^20 ≈ 0.286,
    so prevalence at the end of the band = 0.30 + (1 - 0.30) * 0.286
    = 0.30 + 0.200 ≈ 0.50. Marginal preserved to 1 part in 1000.
    """
    out = _derive_annual_incidence_from_prevalence({(40, 59): 0.30, (60, 79): 0.50})
    lam = out[(40, 59)]
    width = 59 - 40 + 1
    survived_susceptible = (1.0 - lam) ** width
    recovered_p_next = 1.0 - 0.70 * survived_susceptible
    assert abs(recovered_p_next - 0.50) < 1e-3


def test_derive_decreasing_prevalence_zero_rate() -> None:
    """If a later band has LOWER prevalence (survivorship / rare), the
    from-band gets λ=0, not a negative rate."""
    out = _derive_annual_incidence_from_prevalence({(60, 79): 0.50, (80, 99): 0.45})
    assert out[(60, 79)] == 0.0


def test_derive_single_band_rate_is_zero() -> None:
    out = _derive_annual_incidence_from_prevalence({(60, 99): 0.08})
    assert out[(60, 99)] == 0.0


# ---------------------------------------------------------------------------
# _annual_chronic_onset behaviour
# ---------------------------------------------------------------------------


def test_chronic_onset_skips_persons_under_18() -> None:
    p = _alive("PT-TEEN", age=16, sex="M")
    before = list(p.chronic_conditions)
    # Force a table with λ=1 to prove the age gate alone blocks onset.
    table = {"X99": _spec("", {(0, 99): 1.0})}
    _annual_chronic_onset(p, 2026, np.random.default_rng(0), table)
    assert p.chronic_conditions == before


def test_chronic_onset_skips_already_present_icd() -> None:
    p = _alive("PT-HAS", age=50, sex="M")
    p.chronic_conditions.append("I10")
    table = {"I10": _spec("", {(40, 59): 1.0})}
    _annual_chronic_onset(p, 2026, np.random.default_rng(0), table)
    # Not re-appended; stays a single entry.
    assert p.chronic_conditions == ["I10"]


def test_chronic_onset_respects_sex_gate() -> None:
    """Male-locked ICD (e.g. N40 BPH) never fires on a female person."""
    p = _alive("PT-F", age=70, sex="F")
    table = {"N40": _spec("M", {(50, 99): 1.0})}
    _annual_chronic_onset(p, 2026, np.random.default_rng(0), table)
    assert p.chronic_conditions == []


def test_chronic_onset_deterministic_across_runs() -> None:
    """Same (person_id, year) → same decision."""
    table = {"I10": _spec("", {(40, 59): 0.5})}
    p1 = _alive("PT-DET", age=50)
    p2 = _alive("PT-DET", age=50)
    for p in (p1, p2):
        _annual_chronic_onset(
            p,
            2026,
            np.random.default_rng(aging_sub_seed(p.person_id, 2026, "_annual_chronic_onset")),
            table,
        )
    assert p1.chronic_conditions == p2.chronic_conditions


def test_chronic_onset_approximate_marginal_over_decade() -> None:
    """Monte-Carlo integration test: 2000 susceptible 40-year-olds
    aged 20 years with the derived λ should land near P_next within
    sampling noise."""
    rng = np.random.default_rng(12345)
    n = 2000
    cohort = [
        PersonRecord(
            person_id=f"PT-{i:04d}",
            household_id="HH-1",
            age=40,
            sex="M",
            date_of_birth=date(2026 - 40, 1, 1),
        )
        for i in range(n)
    ]
    table = {"I10": _spec("", _derive_annual_incidence_from_prevalence({(40, 59): 0.30, (60, 79): 0.50}))}
    # Seed each person with 0.30 initial prevalence (what the initial
    # cohort sampler would have done at age 40 in band [40, 59]).
    for p in cohort:
        if rng.random() < 0.30:
            p.chronic_conditions.append("I10")
    initial_prev = sum("I10" in p.chronic_conditions for p in cohort) / n
    # Age 20 years. Each year the person stays in band [40, 59] (we
    # cap at age 59 so they do not cross into the no-incidence band).
    for yr in range(20):
        for p in cohort:
            sub_rng = np.random.default_rng(aging_sub_seed(p.person_id, 2026 + yr, "_annual_chronic_onset"))
            _annual_chronic_onset(p, 2026 + yr, sub_rng, table)
    final_prev = sum("I10" in p.chronic_conditions for p in cohort) / n
    assert 0.25 < initial_prev < 0.35
    # Target 0.50 ± 0.05 sampling noise band.
    assert 0.45 < final_prev < 0.55, f"final_prev={final_prev}"


# ---------------------------------------------------------------------------
# Locale loader smoke
# ---------------------------------------------------------------------------


def test_load_annual_incidence_for_us_populates_i10() -> None:
    """US demographics should produce an I10 entry whose first-band
    rate is > 0 (since prev climbs from 0.05 → 0.30 → 0.50 → 0.65)."""
    table = _load_annual_incidence_for_locale("us")
    assert "I10" in table
    spec = table["I10"]
    assert spec.sex == ""
    assert spec.rate_at(30) > 0.0
    assert spec.rate_at(95) == 0.0  # last band


def test_load_annual_incidence_for_jp_populates_i10() -> None:
    table = _load_annual_incidence_for_locale("jp")
    assert "I10" in table


def test_full_advance_population_runs_against_real_locale() -> None:
    """Integration smoke: a small registry walks through
    ``advance_population`` with locale='us' and acquires at least one
    new chronic condition across 20 years for 100 adults."""
    cohort = [_alive(f"PT-{i:04d}", age=40, sex="M") for i in range(100)]
    reg = _registry(cohort)
    for yr in range(20):
        advance_population(reg, 2026 + yr, "us")
    # Over 2000 person-years with multiple non-zero-rate ICDs, we
    # expect at least a handful of acquisitions. The band-diff math
    # pushes I10 alone to ~0.46 cumulative over the band, so a 100-
    # person cohort will see ~46 I10 acquisitions on average.
    total_new = sum(len(p.chronic_conditions) for p in cohort)
    assert total_new >= 10, f"total_new={total_new} suspiciously low"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _spec(sex: str, bands: dict[tuple[int, int], float]):
    """Build a ``_ChronicIncidenceSpec`` without re-importing the
    frozen dataclass by name — the tests only need the public
    attribute surface."""
    from clinosim.modules.population.aging import _ChronicIncidenceSpec

    return _ChronicIncidenceSpec(sex=sex, bands=bands)
