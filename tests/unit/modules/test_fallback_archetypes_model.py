"""The fallback clinical-course archetypes are validated at load by a model."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from clinosim.datafiles import load_data_yaml
from clinosim.modules.clinical_course import engine

pytestmark = pytest.mark.unit


def _yaml() -> dict:
    return load_data_yaml(Path(engine.__file__).resolve().parent / "reference_data" / "fallback_archetypes.yaml")


def test_the_shipped_archetypes_validate() -> None:
    engine._FallbackArchetypes.model_validate(_yaml())


def test_an_unknown_state_variable_fails() -> None:
    data = _yaml()
    first = next(iter(data["archetypes"]))
    bad = {**data["archetypes"][first], "trajectory": {"inflamation_level": {0: 0.1}}}
    with pytest.raises(ValidationError):
        engine._FallbackArchetypes.model_validate({**data, "archetypes": {**data["archetypes"], first: bad}})


def test_probabilities_must_sum_to_one() -> None:
    data = _yaml()
    first = next(iter(data["archetypes"]))
    bad = {**data["archetypes"][first], "probability": 0.0}
    with pytest.raises(ValidationError):
        engine._FallbackArchetypes.model_validate({**data, "archetypes": {**data["archetypes"], first: bad}})
