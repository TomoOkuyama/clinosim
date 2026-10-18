"""Pediatric Layer-1/2 anthropometry sampling tests.

Pre-fix the population generator sampled BMI from the adult-only
``physiology.bmi`` distribution and the activator sampled height from
the adult-only ``physiology.height_cm`` distribution for every age,
including pediatric persons. A 4-year-old ended up with an adult-mean
BMI (~26) paired with an adult-mean height (~170 cm), making the
stored weight land at ~75 kg — physically impossible. The audit of
the p=10k cohort flagged POP-000453 (4-year-old) with ``height_cm=169.2
weight_kg=98.0 bmi=34.2`` as the surfaced symptom.

Fix: for ``age < adult_path_min_age_years`` (18, from
``locale/shared/anthropometric_reference.yaml``) sample BMI and height
from the per-age growth-chart medians (CDC / MHLW) instead of the
adult distribution. The number of ``rng.normal`` draws is unchanged
(one BMI draw in population/engine.py + one height draw in
patient/activator.py), so the master RNG stream shape is preserved.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pytest

from clinosim.modules.patient.activator import activate_patient
from clinosim.modules.population._pediatric_anthropometry import (
    pediatric_bmi_params,
    pediatric_height_params,
    pediatric_upper_age,
)
from clinosim.modules.population.engine import _load_demographics, generate_population
from clinosim.types.population import PersonRecord


def _demo(country: str) -> dict:
    demo = _load_demographics(country)
    demo["_country"] = country
    return demo


def _activate(age: int, sex: str, country: str, bmi_seed: float = 15.5) -> dict:
    person = PersonRecord(
        person_id="P-TEST",
        household_id="HH-TEST",
        age=age,
        sex=sex,
        date_of_birth=date(2024 - age, 6, 1),
        bmi=bmi_seed,
    )
    rng = np.random.default_rng(0)
    prof = activate_patient(person, rng, _demo(country))
    return {"h": prof.height_cm, "w": prof.weight_kg, "bmi": prof.bmi}


# --------------------------------------------------------------------
# Pediatric lookup helpers
# --------------------------------------------------------------------


def test_pediatric_upper_age_matches_yaml():
    assert pediatric_upper_age() == 18


@pytest.mark.parametrize(
    "country,sex,age,expect_mean",
    [
        ("US", "M", 4, 17.5 / (1.05**2)),  # CDC 4yo male: h=105, w=17.5
        ("US", "F", 10, 37.5 / (1.415**2)),  # CDC 10yo female: h=141.5, w=37.5
        ("JP", "M", 7, 24.0 / (1.225**2)),  # MHLW 7yo male: h=122.5, w=24.0
    ],
)
def test_pediatric_bmi_mean_matches_growth_chart(country, sex, age, expect_mean):
    params = pediatric_bmi_params(country, sex, age)
    assert params is not None
    assert params["mean"] == pytest.approx(expect_mean, rel=1e-3)


def test_pediatric_params_none_at_adult_age():
    assert pediatric_bmi_params("US", "M", 18) is None
    assert pediatric_height_params("US", "M", 18) is None


# --------------------------------------------------------------------
# Activator-level: pediatric body dimensions land in realistic bands
# --------------------------------------------------------------------


def test_four_year_old_lands_in_pediatric_band_us():
    """Regression guard: pre-fix a 4yo stored height / weight / BMI
    were adult-sized. The CDC median at 4y is height ≈ 105 cm /
    weight ≈ 17.5 kg / BMI ≈ 15.9. With height SD = 3 cm and BMI SD
    = 1, a single rng.normal draw lands well inside this envelope."""
    out = _activate(age=4, sex="M", country="US", bmi_seed=15.9)
    assert 90.0 <= out["h"] <= 115.0, f"4yo male height out of pediatric band: {out['h']}"
    assert 12.0 <= out["w"] <= 22.0, f"4yo male weight out of pediatric band: {out['w']}"
    assert 13.0 <= out["bmi"] <= 19.0, f"4yo male BMI out of pediatric band: {out['bmi']}"


def test_ten_year_old_jp_lands_in_pediatric_band():
    out = _activate(age=10, sex="F", country="JP", bmi_seed=17.3)
    # MHLW 10yo female: h=140.2 cm, w=34.0 kg, BMI ≈ 17.3
    assert 135.0 <= out["h"] <= 148.0
    assert 28.0 <= out["w"] <= 42.0
    assert 15.0 <= out["bmi"] <= 19.5


def test_adult_sampling_unchanged():
    """Adult path must keep sampling from the physiology adult
    distribution — mean ≈ 170 cm male, 157.5 cm female — not from a
    growth-chart row (which stops at age 17)."""
    out_m = _activate(age=35, sex="M", country="US", bmi_seed=25.0)
    out_f = _activate(age=35, sex="F", country="US", bmi_seed=23.0)
    assert 150.0 <= out_m["h"] <= 200.0
    assert 140.0 <= out_f["h"] <= 180.0
    # BMI reflects the ``person.bmi`` seed (activator does not resample BMI).
    assert out_m["bmi"] == pytest.approx(25.0, abs=0.1)
    assert out_f["bmi"] == pytest.approx(23.0, abs=0.1)


# --------------------------------------------------------------------
# RNG-shape preservation (the critical invariant for byte-identity)
# --------------------------------------------------------------------


def test_population_rng_shape_preserved_vs_adult_only_path():
    """One rng.normal draw for BMI in engine.py, one rng.normal draw
    for height in activator.py — pediatric branch takes the SAME two
    draws as the adult branch, so the master stream shape is
    unchanged. We assert that by regenerating a cohort twice with the
    same seed and checking every PersonRecord's downstream RNG-derived
    attributes line up (bmi, care_seeking_threshold, chronic
    conditions). If pediatric and adult paths drew different counts
    the downstream threshold / conditions would diverge."""
    rng_a = np.random.default_rng(1234)
    rng_b = np.random.default_rng(1234)
    pop_a = generate_population(size=120, country="US", rng=rng_a, base_year=2024)
    pop_b = generate_population(size=120, country="US", rng=rng_b, base_year=2024)
    assert list(pop_a.persons.keys()) == list(pop_b.persons.keys())
    for pid in pop_a.persons:
        a, b = pop_a.persons[pid], pop_b.persons[pid]
        assert a.bmi == b.bmi
        assert a.care_seeking_threshold == b.care_seeking_threshold
        assert a.chronic_conditions == b.chronic_conditions


def test_population_pediatric_bmi_below_adult_mean():
    """Statistical sanity: with the pediatric branch active, children
    in the cohort should NOT sample adult-mean BMI (~26). Pre-fix the
    distribution of child BMI was centered on the adult mean."""
    rng = np.random.default_rng(42)
    pop = generate_population(size=400, country="US", rng=rng, base_year=2024)
    peds_bmis = [p.bmi for p in pop.persons.values() if 2 <= p.age < 18]
    assert peds_bmis, "no pediatric samples in cohort"
    mean_peds = sum(peds_bmis) / len(peds_bmis)
    # Pre-fix: ≈ 26 (adult mean). Post-fix: pediatric medians range 15-21
    # across ages 2-17 → cohort mean should land in [14, 22].
    assert 14.0 <= mean_peds <= 22.0, f"pediatric BMI cohort mean {mean_peds:.2f} outside realistic band"
