"""Issue #2767: the newborn screening YAML is validated at load."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from clinosim.datafiles import load_data_yaml
from clinosim.modules.newborn import engine

pytestmark = pytest.mark.unit


def _yaml() -> dict:
    return load_data_yaml(engine._HERE / "reference_data" / "newborn_screening.yaml")


def test_the_shipped_yaml_validates() -> None:
    engine._NewbornConfig.model_validate(_yaml())


def test_an_unregistered_screen_code_fails() -> None:
    data = _yaml()
    with pytest.raises(ValidationError):
        engine._NewbornConfig.model_validate(
            {**data, "hearing_screen": {**data["hearing_screen"], "procedure_code": "1"}}
        )


def test_screen_weights_must_be_pass_and_refer() -> None:
    data = _yaml()
    screen = {**data["metabolic_screen"], "result_weights": {"pass": 0.9, "fail": 0.1}}
    with pytest.raises(ValidationError):
        engine._NewbornConfig.model_validate({**data, "metabolic_screen": screen})


def test_drug_codes_come_from_the_catalog_not_this_file() -> None:
    data = _yaml()
    with pytest.raises(ValidationError):
        engine._NewbornConfig.model_validate(
            {**data, "vitamin_k": {**data["vitamin_k"], "jp": {**data["vitamin_k"]["jp"], "yj_code": "3160002Q1040"}}}
        )
