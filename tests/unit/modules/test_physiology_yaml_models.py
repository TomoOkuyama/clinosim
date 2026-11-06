"""The physiology reference YAML files are validated at load by models."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from clinosim.datafiles import load_data_yaml
from clinosim.modules.physiology import engine

pytestmark = pytest.mark.unit

_REF = Path(engine.__file__).resolve().parent / "reference_data"


def test_the_shipped_files_validate() -> None:
    engine._GlycemicThresholds.model_validate(load_data_yaml(_REF / "chronic_glycemic_thresholds.yaml"))
    engine._StateVariableRanges.model_validate(load_data_yaml(_REF / "state_variable_ranges.yaml"))


def test_an_unknown_state_variable_fails() -> None:
    data = load_data_yaml(_REF / "state_variable_ranges.yaml")
    with pytest.raises(ValidationError):
        engine._StateVariableRanges.model_validate({**data, "variables": {"inflamation_level": {"min": 0, "max": 1}}})


def test_an_inverted_range_fails() -> None:
    data = load_data_yaml(_REF / "state_variable_ranges.yaml")
    with pytest.raises(ValidationError):
        engine._StateVariableRanges.model_validate({**data, "variables": {"renal_function": {"min": 1, "max": 0}}})


def test_hba1c_constants_must_be_ordered() -> None:
    data = load_data_yaml(_REF / "chronic_glycemic_thresholds.yaml")
    with pytest.raises(ValidationError):
        engine._GlycemicThresholds.model_validate({**data, "hba1c": {**data["hba1c"], "nondm_base": 20.0}})
