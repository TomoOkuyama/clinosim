"""Issue #2760: code-status, device and care-level reference YAML are validated at load."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from clinosim.datafiles import load_data_yaml
from clinosim.modules.care_level import engine as care_level
from clinosim.modules.code_status import engine as code_status
from clinosim.modules.device import engine as device

pytestmark = pytest.mark.unit


def _yaml(module, name: str) -> dict:
    return load_data_yaml(module._REF_DIR / name)


def test_the_shipped_yaml_validates() -> None:
    code_status._CodeStatusConfig.model_validate(_yaml(code_status, "code_status.yaml"))
    care_level._CareLevelConfig.model_validate(_yaml(care_level, "care_level.yaml"))
    device._DevicesConfig.model_validate(_yaml(device, "devices.yaml"))


def test_an_unknown_key_fails() -> None:
    data = {**_yaml(code_status, "code_status.yaml"), "tier": []}
    with pytest.raises(ValidationError):
        code_status._CodeStatusConfig.model_validate(data)


def test_an_unregistered_snomed_code_fails() -> None:
    data = _yaml(device, "devices.yaml")
    data = {**data, "devices": {**data["devices"], "cvc": {**data["devices"]["cvc"], "snomed_code": "999999999"}}}
    with pytest.raises(ValidationError):
        device._DevicesConfig.model_validate(data)


def test_an_unknown_placement_token_fails() -> None:
    data = _yaml(device, "devices.yaml")
    cvc = {**data["devices"]["cvc"], "placement_criteria": [{"any": ["severity_modrate_plus"]}]}
    with pytest.raises(ValidationError):
        device._DevicesConfig.model_validate({**data, "devices": {**data["devices"], "cvc": cvc}})


def test_an_open_ended_care_level_band_fails() -> None:
    data = {**_yaml(care_level, "care_level.yaml"), "age_bands": ["0-64", "65+"]}
    with pytest.raises(ValidationError):
        care_level._CareLevelConfig.model_validate(data)
