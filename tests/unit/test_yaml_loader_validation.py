"""Verify import-time YAML loader validation — _validate_* cross-references.

Mirrors clinosim/modules/observation/microbiology.py:_validate_microbiology
pattern. Each _validate_* raises ValueError on YAML editing accidents
(empty list / negative weight / unknown key / missing SNOMED etc.) so
the silent-no-op (PR-90 class bug) cannot slip through.
"""
from __future__ import annotations

import pytest


# =========================================================================
# Task 2: _validate_hai_organisms (hai/engine.py)
# =========================================================================

def test_validate_hai_organisms_passes_current_yaml():
    """Real production YAML must pass validation (positive baseline).

    Forces cache_clear to ensure _validate_* actually runs on this call
    instead of returning a previously-cached value (test-order robustness).
    """
    from clinosim.modules.hai.engine import load_hai_organisms
    load_hai_organisms.cache_clear()
    data = load_hai_organisms()
    assert "hai_organisms" in data


def test_validate_hai_organisms_rejects_non_dict():
    from clinosim.modules.hai.engine import _validate_hai_organisms
    with pytest.raises(ValueError, match="must be a dict"):
        _validate_hai_organisms([])  # type: ignore[arg-type]


def test_validate_hai_organisms_rejects_unknown_hai_type():
    from clinosim.modules.hai.engine import _validate_hai_organisms
    bad = {"hai_organisms": {"unknown_type": [{"snomed": "123", "weight": 0.5}]}}
    with pytest.raises(ValueError, match="unknown HAI type"):
        _validate_hai_organisms(bad)


def test_validate_hai_organisms_rejects_empty_organism_list():
    from clinosim.modules.hai.engine import _validate_hai_organisms
    bad = {"hai_organisms": {"clabsi": []}}
    with pytest.raises(ValueError, match="empty organism list"):
        _validate_hai_organisms(bad)


def test_validate_hai_organisms_rejects_negative_weight():
    from clinosim.modules.hai.engine import _validate_hai_organisms
    bad = {"hai_organisms": {"clabsi": [{"snomed": "123", "weight": -0.1}]}}
    with pytest.raises(ValueError, match="negative weight"):
        _validate_hai_organisms(bad)


def test_validate_hai_organisms_rejects_zero_sum_weights():
    from clinosim.modules.hai.engine import _validate_hai_organisms
    bad = {"hai_organisms": {"clabsi": [{"snomed": "123", "weight": 0.0}]}}
    with pytest.raises(ValueError, match="zero-sum"):
        _validate_hai_organisms(bad)


def test_validate_hai_organisms_rejects_empty_snomed():
    from clinosim.modules.hai.engine import _validate_hai_organisms
    bad = {"hai_organisms": {"clabsi": [{"snomed": "", "weight": 1.0}]}}
    with pytest.raises(ValueError, match="empty SNOMED"):
        _validate_hai_organisms(bad)


# =========================================================================
# Task 3: _validate_demographics (locale/loader.py)
# =========================================================================

def test_validate_demographics_passes_current_us_yaml():
    """Real US demographics YAML must pass validation."""
    from clinosim.locale.loader import _load_demographics_cached, load_demographics
    _load_demographics_cached.cache_clear()
    data = load_demographics("US")
    assert "_country" in data


def test_validate_demographics_passes_current_jp_yaml():
    from clinosim.locale.loader import _load_demographics_cached, load_demographics
    _load_demographics_cached.cache_clear()
    data = load_demographics("JP")
    assert "_country" in data


def test_validate_demographics_rejects_non_dict():
    from clinosim.locale.loader import _validate_demographics
    with pytest.raises(ValueError, match="must be a dict"):
        _validate_demographics([])  # type: ignore[arg-type]


def test_validate_demographics_rejects_zero_sum_smoking_dist():
    from clinosim.locale.loader import _validate_demographics
    bad = {
        "lifestyle_distribution": {
            "smoking": {"M": {"never": 0.0, "current": 0.0}}
        }
    }
    with pytest.raises(ValueError, match="zero-sum"):
        _validate_demographics(bad)


def test_validate_demographics_rejects_negative_alcohol_weight():
    from clinosim.locale.loader import _validate_demographics
    bad = {
        "lifestyle_distribution": {
            "alcohol": {"F": {"none": 0.5, "heavy": -0.1}}
        }
    }
    with pytest.raises(ValueError, match="negative weight"):
        _validate_demographics(bad)


# =========================================================================
# Task 4: _validate_names + _validate_addresses (locale/loader.py)
# =========================================================================

def test_validate_names_passes_current_us_yaml():
    from clinosim.locale.loader import load_names
    load_names.cache_clear()
    data = load_names("US")
    assert "surnames" in data


def test_validate_names_passes_current_jp_yaml():
    from clinosim.locale.loader import load_names
    load_names.cache_clear()
    data = load_names("JP")
    assert "surnames" in data


def test_validate_names_rejects_non_dict():
    from clinosim.locale.loader import _validate_names
    with pytest.raises(ValueError, match="must be a dict"):
        _validate_names([])  # type: ignore[arg-type]


def test_validate_names_rejects_zero_sum_surname_weights():
    from clinosim.locale.loader import _validate_names
    bad = {"surnames": [{"name": "A", "weight": 0}, {"name": "B", "weight": 0}]}
    with pytest.raises(ValueError, match="zero-sum"):
        _validate_names(bad)


def test_validate_names_rejects_negative_given_name_weight():
    from clinosim.locale.loader import _validate_names
    bad = {
        "surnames": [{"name": "OK", "weight": 1}],
        "given_names_male": [{"name": "Bad", "weight": -1}],
    }
    with pytest.raises(ValueError, match="negative weight"):
        _validate_names(bad)


def test_validate_addresses_passes_current_us_yaml():
    from clinosim.locale.loader import load_addresses
    load_addresses.cache_clear()
    data = load_addresses("US")
    assert "cities" in data


def test_validate_addresses_rejects_non_dict():
    from clinosim.locale.loader import _validate_addresses
    with pytest.raises(ValueError, match="must be a dict"):
        _validate_addresses([])  # type: ignore[arg-type]


def test_validate_addresses_rejects_zero_sum_city_weights():
    from clinosim.locale.loader import _validate_addresses
    bad = {"cities": [{"city": "A", "weight": 0}, {"city": "B", "weight": 0}]}
    with pytest.raises(ValueError, match="zero-sum"):
        _validate_addresses(bad)


def test_validate_addresses_rejects_negative_city_weight():
    from clinosim.locale.loader import _validate_addresses
    bad = {"cities": [{"city": "Bad", "weight": -1}]}
    with pytest.raises(ValueError, match="negative weight"):
        _validate_addresses(bad)


# =========================================================================
# Fix Task 2 (adversarial review Agent 2): structural type defenses,
# non-numeric weight rejection, empty-list tolerance, positive fallback="raise"
# =========================================================================


# ---------- Structural type negative tests ----------

def test_validate_hai_organisms_rejects_non_dict_organism_entry():
    from clinosim.modules.hai.engine import _validate_hai_organisms
    bad = {"hai_organisms": {"clabsi": ["not_a_dict"]}}
    with pytest.raises(ValueError, match="entry must be a dict"):
        _validate_hai_organisms(bad)


def test_validate_hai_organisms_rejects_non_list_organism_list():
    from clinosim.modules.hai.engine import _validate_hai_organisms
    bad = {"hai_organisms": {"clabsi": "not_a_list"}}
    with pytest.raises(ValueError, match="empty organism list"):
        # not-a-list path: validator's `not isinstance(..., list) or not ...`
        # branch catches this as the same "empty organism list" error.
        _validate_hai_organisms(bad)


def test_validate_hai_organisms_rejects_non_dict_organisms_map():
    from clinosim.modules.hai.engine import _validate_hai_organisms
    bad = {"hai_organisms": "not_a_dict"}
    with pytest.raises(ValueError, match="'hai_organisms' must be a dict"):
        _validate_hai_organisms(bad)


def test_validate_demographics_rejects_non_dict_lifestyle():
    from clinosim.locale.loader import _validate_demographics
    bad = {"lifestyle_distribution": "not_a_dict"}
    with pytest.raises(ValueError, match="lifestyle_distribution must be a dict"):
        _validate_demographics(bad)


def test_validate_demographics_rejects_non_dict_smoking_per_sex():
    from clinosim.locale.loader import _validate_demographics
    bad = {"lifestyle_distribution": {"smoking": "not_a_dict"}}
    with pytest.raises(ValueError, match="lifestyle_distribution.smoking must be a dict"):
        _validate_demographics(bad)


def test_validate_demographics_rejects_non_dict_sex_dist():
    from clinosim.locale.loader import _validate_demographics
    bad = {"lifestyle_distribution": {"alcohol": {"M": "not_a_dict"}}}
    with pytest.raises(ValueError, match="must be a dict"):
        _validate_demographics(bad)


def test_validate_names_rejects_non_list_surnames():
    from clinosim.locale.loader import _validate_names
    bad = {"surnames": "not_a_list"}
    with pytest.raises(ValueError, match="must be a list"):
        _validate_names(bad)


def test_validate_names_rejects_non_dict_surname_entry():
    from clinosim.locale.loader import _validate_names
    bad = {"surnames": ["not_a_dict"]}
    with pytest.raises(ValueError, match="entry must be a dict"):
        _validate_names(bad)


def test_validate_addresses_rejects_non_list_cities():
    from clinosim.locale.loader import _validate_addresses
    bad = {"cities": "not_a_list"}
    with pytest.raises(ValueError, match="must be a list"):
        _validate_addresses(bad)


def test_validate_addresses_rejects_non_dict_city_entry():
    from clinosim.locale.loader import _validate_addresses
    bad = {"cities": ["not_a_dict"]}
    with pytest.raises(ValueError, match="entry must be a dict"):
        _validate_addresses(bad)


# ---------- Non-numeric weight tests ----------

def test_validate_hai_organisms_rejects_non_numeric_weight():
    from clinosim.modules.hai.engine import _validate_hai_organisms
    bad = {"hai_organisms": {"clabsi": [{"snomed": "123", "weight": "not-a-number"}]}}
    with pytest.raises(ValueError, match="non-numeric"):
        _validate_hai_organisms(bad)


def test_validate_demographics_rejects_non_numeric_weight():
    from clinosim.locale.loader import _validate_demographics
    bad = {"lifestyle_distribution": {"smoking": {"M": {"never": "bad"}}}}
    with pytest.raises(ValueError, match="non-numeric"):
        _validate_demographics(bad)


def test_validate_names_rejects_non_numeric_weight():
    from clinosim.locale.loader import _validate_names
    bad = {"surnames": [{"name": "A", "weight": "bad"}]}
    with pytest.raises(ValueError, match="non-numeric"):
        _validate_names(bad)


def test_validate_addresses_rejects_non_numeric_weight():
    from clinosim.locale.loader import _validate_addresses
    bad = {"cities": [{"city": "A", "weight": "bad"}]}
    with pytest.raises(ValueError, match="non-numeric"):
        _validate_addresses(bad)


# ---------- Empty-list positive tests (spec/impl alignment) ----------

def test_validate_names_accepts_empty_surnames():
    """Implementation tolerates empty lists (upstream normalize_probabilities
    raises on empty array anyway). Verify validator does NOT raise."""
    from clinosim.locale.loader import _validate_names
    _validate_names({"surnames": []})  # Must not raise


def test_validate_names_accepts_missing_lists():
    """All three name lists are optional; absent keys are valid."""
    from clinosim.locale.loader import _validate_names
    _validate_names({})  # Must not raise


def test_validate_addresses_accepts_empty_cities():
    """Implementation tolerates empty cities (upstream guard handles)."""
    from clinosim.locale.loader import _validate_addresses
    _validate_addresses({"cities": []})  # Must not raise


def test_validate_addresses_accepts_missing_cities():
    """cities key is optional."""
    from clinosim.locale.loader import _validate_addresses
    _validate_addresses({})  # Must not raise


def test_validate_demographics_accepts_missing_lifestyle():
    """lifestyle_distribution is optional; absent block is valid."""
    from clinosim.locale.loader import _validate_demographics
    _validate_demographics({"average_household_size": 2.5})  # Must not raise


# ---------- Positive normalize_probabilities(fallback="raise") test ----------

def test_normalize_probabilities_raise_mode_passes_valid_input():
    """Verify fallback="raise" does NOT raise on valid (positive-sum) input —
    raises only on zero/negative sum. This guards against accidentally
    changing the helper to be over-strict."""
    import numpy as np

    from clinosim.modules._shared import normalize_probabilities
    result = normalize_probabilities([0.5, 0.5], fallback="raise")
    assert np.allclose(result, [0.5, 0.5])
    # Asymmetric weights also OK
    result = normalize_probabilities([1.0, 3.0], fallback="raise")
    assert np.allclose(result, [0.25, 0.75])
    # Single-element array OK
    result = normalize_probabilities([7.0], fallback="raise")
    assert np.allclose(result, [1.0])
