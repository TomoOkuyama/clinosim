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
    """Real production YAML must pass validation (positive baseline)."""
    from clinosim.modules.hai.engine import load_hai_organisms
    # Triggers _validate_hai_organisms on first call (via lru_cache loader).
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
    from clinosim.locale.loader import load_demographics
    data = load_demographics("US")
    assert "_country" in data


def test_validate_demographics_passes_current_jp_yaml():
    from clinosim.locale.loader import load_demographics
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
    data = load_names("US")
    assert "surnames" in data


def test_validate_names_passes_current_jp_yaml():
    from clinosim.locale.loader import load_names
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
