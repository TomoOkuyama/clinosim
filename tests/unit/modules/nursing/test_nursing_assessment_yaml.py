"""YAML validator tests for nursing_assessment.yaml (Tier 1 #3 α-min-2 Task 4)."""

from __future__ import annotations

import pytest

from clinosim.modules.nursing.engine import (
    _validate_nursing_assessment,
    load_nursing_assessment,
)


def test_yaml_loads():
    a = load_nursing_assessment()
    assert a


def test_validator_raises_on_empty():
    with pytest.raises(ValueError, match="empty"):
        _validate_nursing_assessment({})


def test_validator_raises_on_missing_adl_categories():
    bad = {
        "risk_assessments": {},
        "disease_specific_nursing_focus": {},
        "baseline": {"focus": "f", "interventions_ja": []},
    }
    with pytest.raises(ValueError, match="adl_categories"):
        _validate_nursing_assessment(bad)


def test_validator_raises_on_missing_risk_assessments():
    bad = {
        "adl_categories": {},
        "disease_specific_nursing_focus": {},
        "baseline": {"focus": "f", "interventions_ja": []},
    }
    with pytest.raises(ValueError, match="risk_assessments"):
        _validate_nursing_assessment(bad)


def test_validator_raises_on_missing_baseline():
    bad = {
        "adl_categories": {},
        "risk_assessments": {},
        "disease_specific_nursing_focus": {},
    }
    with pytest.raises(ValueError, match="baseline"):
        _validate_nursing_assessment(bad)


def test_validator_raises_on_adl_forward_drift():
    """ADL key not in SUPPORTED_ADL_CATEGORIES → extra key drift."""
    bad = {
        "adl_categories": {
            "eating": [],
            "bathing": [],
            "dressing": [],
            "toileting": [],
            "mobility": [],
            "unknown_adl": [],  # extra
        },
        "risk_assessments": {
            "fall_risk": [],
            "pressure_ulcer_risk": [],
            "aspiration_risk": [],
        },
        "disease_specific_nursing_focus": {},
        "baseline": {"focus": "f", "interventions_ja": []},
    }
    with pytest.raises(ValueError, match="adl_categories.*drift|drift.*adl_categories"):
        _validate_nursing_assessment(bad)


def test_validator_raises_on_adl_reverse_drift():
    """Missing ADL key → reverse drift."""
    bad = {
        "adl_categories": {
            "eating": [],
            "bathing": [],  # missing dressing, toileting, mobility
        },
        "risk_assessments": {
            "fall_risk": [],
            "pressure_ulcer_risk": [],
            "aspiration_risk": [],
        },
        "disease_specific_nursing_focus": {},
        "baseline": {"focus": "f", "interventions_ja": []},
    }
    with pytest.raises(ValueError, match="adl_categories.*drift|drift.*adl_categories"):
        _validate_nursing_assessment(bad)


def test_validator_raises_on_risk_forward_drift():
    """Risk key not in SUPPORTED_RISK_ASSESSMENTS → extra key drift."""
    bad = {
        "adl_categories": {
            "eating": [],
            "bathing": [],
            "dressing": [],
            "toileting": [],
            "mobility": [],
        },
        "risk_assessments": {
            "fall_risk": [],
            "pressure_ulcer_risk": [],
            "aspiration_risk": [],
            "unknown_risk": [],  # extra
        },
        "disease_specific_nursing_focus": {},
        "baseline": {"focus": "f", "interventions_ja": []},
    }
    with pytest.raises(ValueError, match="risk_assessments.*drift|drift.*risk_assessments"):
        _validate_nursing_assessment(bad)


def test_validator_raises_on_disease_entry_missing_focus():
    bad = {
        "adl_categories": {
            "eating": [],
            "bathing": [],
            "dressing": [],
            "toileting": [],
            "mobility": [],
        },
        "risk_assessments": {
            "fall_risk": [],
            "pressure_ulcer_risk": [],
            "aspiration_risk": [],
        },
        "disease_specific_nursing_focus": {
            "bacterial_pneumonia": {"interventions_ja": ["test"]},  # missing focus
        },
        "baseline": {"focus": "f", "interventions_ja": []},
    }
    with pytest.raises(ValueError, match="focus"):
        _validate_nursing_assessment(bad)


def test_validator_raises_on_disease_entry_interventions_not_list():
    bad = {
        "adl_categories": {
            "eating": [],
            "bathing": [],
            "dressing": [],
            "toileting": [],
            "mobility": [],
        },
        "risk_assessments": {
            "fall_risk": [],
            "pressure_ulcer_risk": [],
            "aspiration_risk": [],
        },
        "disease_specific_nursing_focus": {
            "bacterial_pneumonia": {"focus": "f", "interventions_ja": "not_a_list"},
        },
        "baseline": {"focus": "f", "interventions_ja": []},
    }
    with pytest.raises(ValueError, match="interventions_ja.*list|list.*interventions_ja"):
        _validate_nursing_assessment(bad)


def test_validator_raises_on_baseline_missing_focus():
    bad = {
        "adl_categories": {
            "eating": [],
            "bathing": [],
            "dressing": [],
            "toileting": [],
            "mobility": [],
        },
        "risk_assessments": {
            "fall_risk": [],
            "pressure_ulcer_risk": [],
            "aspiration_risk": [],
        },
        "disease_specific_nursing_focus": {},
        "baseline": {"interventions_ja": []},  # missing focus
    }
    with pytest.raises(ValueError, match="baseline.*focus|focus.*baseline"):
        _validate_nursing_assessment(bad)


def test_cached_lru():
    """@lru_cache(maxsize=1) — 2 calls same object."""
    assert load_nursing_assessment() is load_nursing_assessment()
