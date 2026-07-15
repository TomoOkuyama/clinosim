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
