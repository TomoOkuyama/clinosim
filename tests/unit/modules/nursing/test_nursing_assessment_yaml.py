"""YAML validator tests for nursing_assessment.yaml (Tier 1 #3 α-min-2 Task 4)."""

from __future__ import annotations

import pytest

from clinosim.modules.nursing.engine import NursingAssessment, load_nursing_assessment


def test_yaml_loads():
    a = load_nursing_assessment()
    assert a


def test_validator_raises_on_empty():
    with pytest.raises(ValueError, match="empty"):
        NursingAssessment.model_validate({})


def test_validator_raises_on_missing_adl_categories():
    bad = {
        "risk_assessments": {},
        "disease_specific_nursing_focus": {},
        "baseline": {"focus": "f", "interventions": {"ja": []}},
    }
    with pytest.raises(ValueError, match="adl_categories"):
        NursingAssessment.model_validate(bad)


def test_validator_raises_on_missing_risk_assessments():
    bad = {
        "adl_categories": {},
        "disease_specific_nursing_focus": {},
        "baseline": {"focus": "f", "interventions": {"ja": []}},
    }
    with pytest.raises(ValueError, match="risk_assessments"):
        NursingAssessment.model_validate(bad)


def test_validator_raises_on_missing_baseline():
    bad = {
        "adl_categories": {},
        "risk_assessments": {},
        "disease_specific_nursing_focus": {},
    }
    with pytest.raises(ValueError, match="baseline"):
        NursingAssessment.model_validate(bad)


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
        "baseline": {"focus": "f", "interventions": {"ja": []}},
    }
    with pytest.raises(ValueError, match="adl_categories.*drift|drift.*adl_categories"):
        NursingAssessment.model_validate(bad)


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
        "baseline": {"focus": "f", "interventions": {"ja": []}},
    }
    with pytest.raises(ValueError, match="adl_categories.*drift|drift.*adl_categories"):
        NursingAssessment.model_validate(bad)


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
        "baseline": {"focus": "f", "interventions": {"ja": []}},
    }
    with pytest.raises(ValueError, match="risk_assessments.*drift|drift.*risk_assessments"):
        NursingAssessment.model_validate(bad)


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
            "bacterial_pneumonia": {"interventions": {"ja": ["test"]}},  # missing focus
        },
        "baseline": {"focus": "f", "interventions": {"ja": []}},
    }
    with pytest.raises(ValueError, match="focus"):
        NursingAssessment.model_validate(bad)


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
            "bacterial_pneumonia": {"focus": "f", "interventions": {"ja": "not_a_list"}},
        },
        "baseline": {"focus": "f", "interventions": {"ja": []}},
    }
    with pytest.raises(ValueError, match="interventions.*list|list.*interventions_ja"):
        NursingAssessment.model_validate(bad)


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
        "baseline": {"interventions": {"ja": []}},  # missing focus
    }
    with pytest.raises(ValueError, match="baseline.*focus|focus.*baseline"):
        NursingAssessment.model_validate(bad)


def test_cached_lru():
    """@lru_cache(maxsize=1) — 2 calls same object."""
    assert load_nursing_assessment() is load_nursing_assessment()


def _shipped() -> dict:
    import copy

    return copy.deepcopy(load_nursing_assessment())


@pytest.mark.parametrize(
    ("break_it", "message"),
    [
        (lambda d: d["risk_assessments"].pop("fall_risk"), "risk_assessments.*drift"),
        (lambda d: d["baseline"].pop("interventions"), "baseline.interventions"),
        (lambda d: d["baseline"].update({"interventions": {}}), "interventions must map each language to a list"),
        (lambda d: d["disease_specific_nursing_focus"].update({"x": {"focus": "f"}}), "interventions"),
        (lambda d: d["disease_specific_nursing_focus"].update({"x": "not a dict"}), "disease_specific_nursing_focus.x"),
        (lambda d: d.update({"baseline": None}), "baseline"),
    ],
)
def test_validator_rejects_each_broken_section(break_it, message):
    data = _shipped()
    break_it(data)
    with pytest.raises(ValueError, match=message):
        NursingAssessment.model_validate(data)
