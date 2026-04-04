"""Unit tests for observation engine (Layer 3 noise)."""

import numpy as np
import pytest

from clinosim.modules.observation.engine import (
    ANALYTICAL_CV,
    BIOLOGICAL_CV,
    apply_realistic_variability,
    determine_flag,
    generate_lab_result,
    round_to_precision,
)


@pytest.fixture
def rng():
    return np.random.default_rng(42)


@pytest.mark.unit
class TestVariability:
    def test_value_changes_with_noise(self, rng):
        results = [apply_realistic_variability("CRP", 50.0, rng) for _ in range(100)]
        assert min(results) != max(results)  # values should vary
        assert all(r >= 0 for r in results)  # never negative

    def test_low_cv_items_vary_less(self, rng):
        na_results = [apply_realistic_variability("Na", 140.0, rng) for _ in range(100)]
        crp_results = [apply_realistic_variability("CRP", 50.0, rng) for _ in range(100)]

        na_cv = np.std(na_results) / np.mean(na_results)
        crp_cv = np.std(crp_results) / np.mean(crp_results)
        assert crp_cv > na_cv * 2  # CRP varies much more than Na

    def test_zero_value_returns_zero(self, rng):
        assert apply_realistic_variability("CRP", 0.0, rng) == 0.0


@pytest.mark.unit
class TestPrecision:
    def test_rounding(self):
        assert round_to_precision("Na", 140.456) == 140.0  # Na: 0 decimals
        assert round_to_precision("K", 4.567) == 4.6  # K: 1 decimal
        assert round_to_precision("Creatinine", 1.234) == 1.23  # Cr: 2 decimals


@pytest.mark.unit
class TestFlags:
    def test_high_flag(self):
        assert determine_flag("CRP", 50.0) == "H"

    def test_low_flag(self):
        assert determine_flag("Hb", 10.0, sex="M") == "L"  # below male ref range (13.5)

    def test_normal_no_flag(self):
        assert determine_flag("Na", 140.0) is None

    def test_critical_k(self):
        assert determine_flag("K", 7.0) == "critical"

    def test_critical_low_hb(self):
        assert determine_flag("Hb", 6.0) == "critical"  # below panic threshold 7.0
