"""Unit tests for normalize_probabilities helper (PR-A Task 3)."""
import numpy as np
import pytest

from clinosim.modules._shared import normalize_probabilities


@pytest.mark.unit
def test_already_normalized_is_byte_identical_to_plain_asarray():
    """Idempotency on normalized input — load-bearing for byte-diff invariance."""
    probs = [0.2, 0.3, 0.5]
    result = normalize_probabilities(probs)
    expected = np.asarray(probs, dtype=float)
    assert np.array_equal(result, expected)


@pytest.mark.unit
def test_non_normalized_input_is_normalized():
    probs = [1.0, 2.0, 1.0]
    result = normalize_probabilities(probs)
    assert np.isclose(result.sum(), 1.0)
    assert np.allclose(result, [0.25, 0.5, 0.25])


@pytest.mark.unit
def test_numpy_array_input_works_same_as_list():
    probs = np.array([0.25, 0.25, 0.25, 0.25])
    result = normalize_probabilities(probs)
    assert np.array_equal(result, probs)


@pytest.mark.unit
def test_zero_sum_input_falls_back_to_uniform():
    probs = [0.0, 0.0, 0.0]
    result = normalize_probabilities(probs)
    assert np.isclose(result.sum(), 1.0)
    assert np.allclose(result, [1 / 3, 1 / 3, 1 / 3])


@pytest.mark.unit
def test_zero_sum_input_with_raise_fallback_raises():
    with pytest.raises(ValueError, match="non-positive sum"):
        normalize_probabilities([0.0, 0.0, 0.0], fallback="raise")


@pytest.mark.unit
def test_negative_weight_raises():
    with pytest.raises(ValueError, match="negative weight"):
        normalize_probabilities([0.5, -0.1, 0.6])


@pytest.mark.unit
def test_empty_input_falls_back_to_uniform_with_n_equals_1():
    """Edge case: empty list. Uniform fallback returns 1-element [1.0]."""
    result = normalize_probabilities([])
    assert result.tolist() == [1.0]


@pytest.mark.unit
def test_return_type_is_numpy_float64():
    result = normalize_probabilities([1, 2, 3])  # input is int list
    assert result.dtype == np.float64


@pytest.mark.unit
def test_idempotent_after_one_pass():
    """Calling normalize twice returns the same result as calling once."""
    probs = [3.0, 7.0]
    once = normalize_probabilities(probs)
    twice = normalize_probabilities(once)
    assert np.array_equal(once, twice)


@pytest.mark.unit
def test_byte_clean_against_old_arr_divide_arr_sum_pattern():
    """Real-world YAML weights whose float64 sum is not exactly 1.0
    must produce identical output to the old pattern (arr / arr.sum()).

    CAUTI sibling_count_weights [0.27, 0.18, 0.16, 0.13, 0.10, 0.06, 0.10]
    sum to 0.9999... in float64 — NOT exactly 1.0. The helper must be
    byte-identical to the old pre-A3 pattern, NOT byte-identical to the
    input. This verifies the byte-clean migration property claimed in the
    normalize_probabilities docstring.
    """
    probs = [0.27, 0.18, 0.16, 0.13, 0.10, 0.06, 0.10]
    arr = np.asarray(probs, dtype=float)
    old_result = arr / arr.sum()
    new_result = normalize_probabilities(probs)
    assert np.array_equal(new_result, old_result), (
        "normalize_probabilities must be byte-identical to "
        "arr / arr.sum() for CAUTI-style weights summing to 0.9999..."
    )
