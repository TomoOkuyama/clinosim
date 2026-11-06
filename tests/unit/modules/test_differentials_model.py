"""The built-in differentials YAML is validated at load by a model."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from clinosim.datafiles import load_data_yaml
from clinosim.modules.diagnosis import engine

pytestmark = pytest.mark.unit


def _yaml() -> dict:
    return load_data_yaml(engine._REF_DIR / "builtin_differentials.yaml")


def test_the_shipped_tables_validate() -> None:
    engine._DifferentialsConfig.model_validate(_yaml())


def test_an_unregistered_icd_code_fails() -> None:
    data = _yaml()
    bad = {"sepsis": [{"disease": "sepsis", "icd": "A99.99", "prior": 0.5}]}
    with pytest.raises(ValidationError):
        engine._DifferentialsConfig.model_validate({**data, "differentials": bad})


def test_a_prior_above_one_fails() -> None:
    data = _yaml()
    bad = {"sepsis": [{"disease": "sepsis", "icd": "A41.9", "prior": 1.4}]}
    with pytest.raises(ValidationError):
        engine._DifferentialsConfig.model_validate({**data, "differentials": bad})


def test_progression_thresholds_must_rise() -> None:
    data = _yaml()
    with pytest.raises(ValidationError):
        engine._DifferentialsConfig.model_validate(
            {**data, "diagnosis_progression": {"sepsis": [[0.7, "A41.9"], [0.0, "A41.9"]]}}
        )
