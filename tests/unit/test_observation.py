"""Unit tests for observation engine (Layer 3 noise)."""

import numpy as np
import pytest

from clinosim.modules.observation.engine import (
    ANALYTICAL_CV,
    BIOLOGICAL_CV,
    PHYSIOLOGIC_LIMITS,
    apply_realistic_variability,
    determine_flag,
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

    def test_noise_never_exceeds_physiologic_limits(self, rng):
        # Measurement noise on a true value near the upper physiologic edge must
        # not produce life-incompatible observed values (e.g. K 10.5, CRP 663).
        for lab, (lo, hi) in PHYSIOLOGIC_LIMITS.items():
            # Push true value to the upper limit so noise tails would overshoot.
            obs = [apply_realistic_variability(lab, hi, rng) for _ in range(500)]
            assert max(obs) <= hi + 1e-9, f"{lab}: observed {max(obs)} > limit {hi}"
            assert min(obs) >= lo - 1e-9, f"{lab}: observed {min(obs)} < limit {lo}"

    def test_clamp_preserves_in_range_values(self, rng):
        # A mid-range value must still vary (clamp must not collapse normal noise).
        results = [apply_realistic_variability("K", 4.2, rng) for _ in range(100)]
        assert min(results) != max(results)
        assert all(PHYSIOLOGIC_LIMITS["K"][0] <= r <= PHYSIOLOGIC_LIMITS["K"][1] for r in results)


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


@pytest.mark.unit
class TestHbA1cSupport:
    def test_hba1c_in_cv_and_limits(self):
        assert "HbA1c" in BIOLOGICAL_CV
        assert "HbA1c" in ANALYTICAL_CV
        assert "HbA1c" in PHYSIOLOGIC_LIMITS

    def test_hba1c_flag(self):
        assert determine_flag("HbA1c", 8.0) == "H"      # diabetic, above normal range
        assert determine_flag("HbA1c", 5.2) is None     # normal

    def test_baseline_lab_normals_exported(self):
        from clinosim.modules.observation.engine import BASELINE_LAB_NORMALS
        assert BASELINE_LAB_NORMALS["Ca"] == 9.2
        assert BASELINE_LAB_NORMALS["TSH"] == 2.5
        assert "HbA1c" not in BASELINE_LAB_NORMALS    # HbA1c is physiology-modeled now
