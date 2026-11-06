"""The procedure-rules YAML is validated at load by a model."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from clinosim.datafiles import load_data_yaml
from clinosim.modules.procedure import engine

pytestmark = pytest.mark.unit


def _yaml() -> dict:
    return load_data_yaml(Path(engine.__file__).resolve().parent / "reference_data" / "procedure_rules.yaml")


def test_the_shipped_yaml_validates() -> None:
    engine._ProcedureRulesConfig.model_validate(_yaml())


@pytest.mark.parametrize(
    "rule",
    [
        {"diseases": ["sepsiss"], "procedures": {"central_line": 0.5}},  # unknown disease
        {"diseases": ["sepsis"], "procedures": {"central_lien": 0.5}},  # unknown procedure
        {"diseases": ["sepsis"], "procedures": {"central_line": 1.5}},  # not a probability
        {"diseases": ["sepsis"], "procedures": {"central_line": 0.5}, "note": "x"},  # unknown key
    ],
)
def test_a_bad_rule_fails(rule: dict) -> None:
    with pytest.raises(ValidationError):
        engine._ProcedureRulesConfig.model_validate({**_yaml(), "bedside_rules": [rule]})
