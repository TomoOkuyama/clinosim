"""The stage-severity table is validated at load by a model."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from clinosim.datafiles import load_data_yaml
from clinosim.modules.patient import _severity_activation as sev

pytestmark = pytest.mark.unit


def _yaml() -> dict:
    return load_data_yaml(sev._STAGE_SEVERITY_YAML)


def test_the_shipped_table_validates() -> None:
    sev._StageSeverityConfig.model_validate(_yaml())


@pytest.mark.parametrize(
    "stages",
    [{"Stage 1": 0.6, "Stage 2": 0.3}, {"Stage 1": 1.2}, {}],  # decreasing, out of range, empty
)
def test_a_bad_scale_fails(stages: dict) -> None:
    with pytest.raises(ValidationError):
        sev._StageSeverityConfig.model_validate({**_yaml(), "stage_severity": {"I10": stages}})


def test_an_unknown_top_level_key_fails() -> None:
    with pytest.raises(ValidationError):
        sev._StageSeverityConfig.model_validate({**_yaml(), "stage_severities": {}})
