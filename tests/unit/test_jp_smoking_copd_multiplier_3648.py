"""JP couples COPD (J44) to smoking status (Issue #3648)."""

from __future__ import annotations

import numpy as np
import pytest

from clinosim.locale.loaders.demographics import load_demographics
from clinosim.modules.population._chronic import _expected_lifestyle_multiplier
from clinosim.modules.population.engine import generate_population

pytestmark = pytest.mark.unit


def test_jp_demographics_carry_a_smoking_multiplier_for_j44() -> None:
    smoking = load_demographics("JP")["lifestyle_risk_multipliers"]["smoking"]
    assert smoking["current"]["J44"] > smoking["former"]["J44"] > 1.0
    # Only J44 for now: the acute-event keys are not rescaled and would raise JP incidence.
    assert set(smoking["current"]) == {"J44"} and set(smoking["former"]) == {"J44"}


def test_us_block_is_unchanged() -> None:
    smoking = load_demographics("US")["lifestyle_risk_multipliers"]["smoking"]
    assert smoking["current"]["J44"] == 10.0 and smoking["former"]["J44"] == 3.0


def test_expected_multiplier_is_the_probability_weighted_mean() -> None:
    demo = load_demographics("JP")
    smoking = demo["lifestyle_risk_multipliers"]["smoking"]
    e = _expected_lifestyle_multiplier(demo, "J44", "male", 70)
    assert 1.0 < e < smoking["current"]["J44"]
    # the engine rescales by this value, so the J44 marginal is preserved
    assert _expected_lifestyle_multiplier(demo, "J44", "male", 10) == 1.0  # minors are never-smokers


def test_copd_patients_are_less_often_never_smokers_than_adults() -> None:
    demo = load_demographics("JP")
    registry = generate_population(size=6000, country="JP", rng=np.random.default_rng(3648), demo=demo)
    adults = [p for p in registry.persons.values() if p.age >= 40]
    copd = [p for p in adults if "J44" in p.chronic_conditions]
    assert len(copd) >= 40
    never_all = sum(p.smoking_status == "never" for p in adults) / len(adults)
    never_copd = sum(p.smoking_status == "never" for p in copd) / len(copd)
    assert never_copd < never_all - 0.08
