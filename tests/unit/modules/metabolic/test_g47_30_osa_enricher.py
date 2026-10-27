"""G47.30 OSA enricher (Issue #1137 cluster 2 axis 4).

BMI tier x biological sex x age-factor SHA Bernoulli — RNG-neutral
per-person assignment of the G47.30 chronic condition, calibrated to
moderate-to-severe OSA (Peppard 2013). Mirrors axis-3 (K76.0) pattern
(POST_POPULATION, idempotent, byte-identity preserving for
cohorts that happen to hash under the threshold).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from clinosim.modules.metabolic.engine import (
    _bmi_tier,
    _derive_osa_assignment,
    _draw_osa,
    _osa_probability,
    g47_30_osa_enricher,
)
from clinosim.types.population import PersonRecord


@dataclass
class _Ctx:
    population: object
    master_seed: int = 42


class _Pop:
    def __init__(self, persons: dict):
        self.persons = persons


def _person(pid: str, bmi: float, sex: str = "M", chronic: list[str] | None = None) -> PersonRecord:
    return PersonRecord(
        person_id=pid,
        household_id="HH-1",
        age=55,
        sex=sex,
        date_of_birth=date(1971, 1, 1),
        bmi=bmi,
        chronic_conditions=list(chronic or []),
    )


# ---------------------------------------------------------------------------
# BMI tier helper
# ---------------------------------------------------------------------------


def test_bmi_tier_boundaries() -> None:
    assert _bmi_tier(22.0) == "reference"
    assert _bmi_tier(24.9) == "reference"
    assert _bmi_tier(25.0) == "overweight"
    assert _bmi_tier(29.9) == "overweight"
    assert _bmi_tier(30.0) == "obese"
    assert _bmi_tier(39.9) == "obese"
    assert _bmi_tier(40.0) == "morbid"
    assert _bmi_tier(55.0) == "morbid"


# ---------------------------------------------------------------------------
# Pure probability function
# ---------------------------------------------------------------------------


def test_prob_male_tier_anchors() -> None:
    assert _osa_probability(22.0, "M") == 0.02
    assert _osa_probability(27.0, "M") == 0.085
    assert _osa_probability(33.0, "M") == 0.21
    assert _osa_probability(42.0, "M") == 0.315


def test_prob_female_tier_anchors() -> None:
    assert _osa_probability(22.0, "F") == 0.0065
    assert _osa_probability(27.0, "F") == 0.032
    assert _osa_probability(33.0, "F") == 0.08
    assert _osa_probability(42.0, "F") == 0.145


def test_prob_male_approximately_double_female() -> None:
    """Peppard 2013 anchor: at ages 50-70 male moderate-to-severe OSA
    is ~2x female (17% vs 9%)."""
    ratio = _osa_probability(33.0, "M", 55) / _osa_probability(33.0, "F", 55)
    assert 1.8 <= ratio <= 2.3


def test_prob_age_factor_raises_older_adults() -> None:
    assert _osa_probability(33.0, "M", 55) > _osa_probability(33.0, "M", 40)
    assert _osa_probability(33.0, "F", 55) > _osa_probability(33.0, "F", 40)


def test_prob_unknown_sex_falls_back_to_female() -> None:
    """Any non-M-starting value uses the female (conservative)
    table — simulator reserves "M" / "F"; a legacy "unknown"
    should under-identify rather than over-identify."""
    assert _osa_probability(33.0, "X") == 0.08
    assert _osa_probability(33.0, "") == 0.08


# ---------------------------------------------------------------------------
# SHA draw function
# ---------------------------------------------------------------------------


def test_draw_zero_probability_always_false() -> None:
    assert _draw_osa("PT-ANY", 0.0) is False


def test_draw_full_probability_always_true() -> None:
    assert _draw_osa("PT-ANY", 1.0) is True


def test_draw_is_deterministic_per_person() -> None:
    r1 = _draw_osa("PT-DET", 0.5)
    r2 = _draw_osa("PT-DET", 0.5)
    assert r1 == r2


def test_draw_osa_vs_nafld_salts_differ() -> None:
    """The OSA SHA salt differs from the NAFLD salt so a given
    person's OSA / NAFLD assignments are statistically
    independent (not perfectly correlated)."""
    from clinosim.modules.metabolic.engine import _draw_nafld

    agree = 0
    for i in range(200):
        pid = f"PT-{i}"
        if _draw_osa(pid, 0.5) == _draw_nafld(pid, 0.5):
            agree += 1
    # If the two draws were identical (same salt), agree would
    # be 200. Independent draws should land near 100 ±~25.
    assert 60 <= agree <= 140, f"got {agree} / 200 (expected ~100 ±40)"


# ---------------------------------------------------------------------------
# Derivation wrapper
# ---------------------------------------------------------------------------


def test_derive_reference_bmi_mostly_absent() -> None:
    """BMI < 25 male prevalence = 2 % — expect ~10 / 500 assigned."""
    yes = sum(1 for i in range(500) if _derive_osa_assignment(f"PT-R-{i}", 22.0, "M") == "G47.30")
    assert 2 <= yes <= 25, f"got {yes} / 500 (expected ~10)"


def test_derive_morbid_male_high_rate() -> None:
    """Morbid obese male prevalence = 31.5 %."""
    yes = sum(1 for i in range(200) if _derive_osa_assignment(f"PT-M-{i}", 42.0, "M") == "G47.30")
    assert 45 <= yes <= 85, f"got {yes} / 200 (expected ~63)"


# ---------------------------------------------------------------------------
# Enricher behavior
# ---------------------------------------------------------------------------


def test_enricher_idempotent_on_repeat_call() -> None:
    p = _person("PT-REPEAT", bmi=42.0, sex="M")
    ctx = _Ctx(population=_Pop({p.person_id: p}))
    g47_30_osa_enricher(ctx)
    before = p.chronic_conditions.count("G47.30")
    g47_30_osa_enricher(ctx)
    after = p.chronic_conditions.count("G47.30")
    assert before == after


def test_enricher_mixed_cohort_prevalence_in_band() -> None:
    """A 500-person obese-male cohort aged 55 should assign G47.30 to
    roughly 28 % of patients (0.21 x age factor 1.35)."""
    persons = {f"PT-OB-M-{i}": _person(f"PT-OB-M-{i}", bmi=33.0, sex="M") for i in range(500)}
    ctx = _Ctx(population=_Pop(persons))
    g47_30_osa_enricher(ctx)
    assigned = sum(1 for p in persons.values() if "G47.30" in p.chronic_conditions)
    assert 110 <= assigned <= 175, f"got {assigned} / 500 (expected ~142)"


def test_enricher_sex_gradient_visible() -> None:
    """At BMI 33 the male-vs-female prevalence ratio is 2:1.
    500 males + 500 females -> male-assigned should be ~2× female."""
    male_pop = {f"PT-M-{i}": _person(f"PT-M-{i}", bmi=33.0, sex="M") for i in range(500)}
    female_pop = {f"PT-F-{i}": _person(f"PT-F-{i}", bmi=33.0, sex="F") for i in range(500)}
    for pop in (male_pop, female_pop):
        g47_30_osa_enricher(_Ctx(population=_Pop(pop)))

    male_hits = sum(1 for p in male_pop.values() if "G47.30" in p.chronic_conditions)
    female_hits = sum(1 for p in female_pop.values() if "G47.30" in p.chronic_conditions)
    # Approximate 2:1 ratio ±40 %
    ratio = male_hits / max(female_hits, 1)
    assert 1.5 <= ratio <= 2.5, f"ratio {ratio:.2f} (expected ~2.0, male={male_hits}, female={female_hits})"


def test_enricher_rng_neutral_fixed_person_id() -> None:
    """SHA draw depends on person_id, not master seed."""
    p1 = _person("PT-SAME", bmi=42.0, sex="M")
    p2 = _person("PT-SAME", bmi=42.0, sex="M")
    g47_30_osa_enricher(_Ctx(population=_Pop({p1.person_id: p1}), master_seed=1))
    g47_30_osa_enricher(_Ctx(population=_Pop({p2.person_id: p2}), master_seed=999))
    assert ("G47.30" in p1.chronic_conditions) == ("G47.30" in p2.chronic_conditions)
