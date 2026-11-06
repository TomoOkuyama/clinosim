"""Issue #2763: social-history and family-history reference YAML are validated at load."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from clinosim.datafiles import load_data_yaml
from clinosim.modules.family_history import engine as fmh
from clinosim.modules.sdoh import engine as sdoh

pytestmark = pytest.mark.unit


def _sdoh() -> dict:
    return load_data_yaml(sdoh._REF_DIR / "social_history.yaml")


def _fmh() -> dict:
    return load_data_yaml(fmh._REF_DIR / "family_history.yaml")


def test_the_shipped_yaml_validates() -> None:
    sdoh._SocialHistoryConfig.model_validate(_sdoh())
    fmh._FamilyHistoryConfig.model_validate(_fmh())


def test_an_unregistered_snomed_value_fails() -> None:
    data = _sdoh()
    values = {**data["smoking_status"]["values"], "never": {"snomed": "999999999"}}
    with pytest.raises(ValidationError):
        sdoh._SocialHistoryConfig.model_validate(
            {**data, "smoking_status": {**data["smoking_status"], "values": values}}
        )


def test_an_inverted_age_offset_fails() -> None:
    with pytest.raises(ValidationError):
        fmh._FamilyHistoryConfig.model_validate({**_fmh(), "parent_age_offset": {"min": 35, "max": 25}})


def test_an_unknown_sex_restriction_fails() -> None:
    data = _fmh()
    conditions = {**data["conditions"], "C50": {"heritability": 2.0, "sex": "f"}}
    with pytest.raises(ValidationError):
        fmh._FamilyHistoryConfig.model_validate({**data, "conditions": conditions})
