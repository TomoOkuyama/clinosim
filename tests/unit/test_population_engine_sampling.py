"""Unit tests for population/engine.py private sampling helpers.

_sample_blood_type added by the determinism chain (2026-07-04) to route
YAML-sourced blood_type weights through normalize_probabilities(fallback=
"raise"), matching the sibling _sample_age_band / _sample_surname pattern
in this file and closing the one YAML-sourced rng.choice(p=...) call site
that bypassed it (0.40+0.30+0.20+0.10 sums to 0.9999999999999999 in float64).
"""

from __future__ import annotations

import numpy as np
import pytest

pytestmark = pytest.mark.unit


def test_sample_blood_type_returns_valid_key():
    from clinosim.modules.population.engine import _sample_blood_type

    demo = {"blood_type": {"A": 0.40, "O": 0.30, "B": 0.20, "AB": 0.10}}
    rng = np.random.default_rng(0)
    result = _sample_blood_type(demo, rng)
    assert result in {"A", "O", "B", "AB"}


def test_sample_blood_type_deterministic_with_seed():
    from clinosim.modules.population.engine import _sample_blood_type

    demo = {"blood_type": {"A": 0.40, "O": 0.30, "B": 0.20, "AB": 0.10}}
    r1 = _sample_blood_type(demo, np.random.default_rng(42))
    r2 = _sample_blood_type(demo, np.random.default_rng(42))
    assert r1 == r2


def test_sample_blood_type_uses_default_when_demo_missing_key():
    from clinosim.modules.population.engine import _sample_blood_type

    rng = np.random.default_rng(0)
    result = _sample_blood_type({}, rng)
    assert result in {"O", "A", "B", "AB"}


def test_sample_blood_type_raises_on_zero_sum():
    from clinosim.modules.population.engine import _sample_blood_type

    demo = {"blood_type": {"A": 0.0, "O": 0.0}}
    rng = np.random.default_rng(0)
    with pytest.raises(ValueError, match="non-positive sum"):
        _sample_blood_type(demo, rng)


# --- Issue #741: age-conditional sex_ratio ---------------------------------


def test_sex_ratio_male_probability_age_conditional_lookup():
    from clinosim.modules.population.engine import _sex_ratio_male_probability

    demo = {
        "sex_ratio": {
            "male": 0.49,
            "age_conditional": {
                "0-59": 0.510,
                "60-69": 0.490,
                "70-79": 0.455,
                "80-89": 0.382,
                "90-99": 0.229,
            },
        }
    }
    assert _sex_ratio_male_probability(demo, 30) == 0.510
    assert _sex_ratio_male_probability(demo, 65) == 0.490
    assert _sex_ratio_male_probability(demo, 75) == 0.455
    assert _sex_ratio_male_probability(demo, 85) == 0.382
    assert _sex_ratio_male_probability(demo, 95) == 0.229


def test_sex_ratio_male_probability_boundary_ages():
    from clinosim.modules.population.engine import _sex_ratio_male_probability

    demo = {"sex_ratio": {"age_conditional": {"0-59": 0.510, "60-99": 0.400}}}
    # Boundary at 59 → 0-59 band; 60 → 60-99 band.
    assert _sex_ratio_male_probability(demo, 0) == 0.510
    assert _sex_ratio_male_probability(demo, 59) == 0.510
    assert _sex_ratio_male_probability(demo, 60) == 0.400
    assert _sex_ratio_male_probability(demo, 99) == 0.400


def test_sex_ratio_male_probability_falls_back_to_flat_male():
    from clinosim.modules.population.engine import _sex_ratio_male_probability

    demo = {"sex_ratio": {"male": 0.42}}  # no age_conditional
    assert _sex_ratio_male_probability(demo, 40) == 0.42
    assert _sex_ratio_male_probability(demo, 90) == 0.42


def test_sex_ratio_male_probability_falls_back_to_default_when_yaml_missing():
    from clinosim.modules.population._household_thresholds import SEX_RATIO_MALE_DEFAULT
    from clinosim.modules.population.engine import _sex_ratio_male_probability

    assert _sex_ratio_male_probability({}, 40) == SEX_RATIO_MALE_DEFAULT
    # Empty age_conditional block also falls through to the single-male fallback.
    assert _sex_ratio_male_probability({"sex_ratio": {"male": 0.47, "age_conditional": {}}}, 40) == 0.47


def test_sex_ratio_age_conditional_out_of_range_falls_back():
    from clinosim.modules.population.engine import _sex_ratio_male_probability

    demo = {"sex_ratio": {"male": 0.49, "age_conditional": {"0-89": 0.500}}}
    # 90 is outside any declared band → falls back to top-level `male`.
    assert _sex_ratio_male_probability(demo, 90) == 0.49
