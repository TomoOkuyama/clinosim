"""The antibiotic reference YAML files are shape-checked at load by models."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from clinosim.datafiles import load_data_yaml
from clinosim.modules.antibiotic import engine

pytestmark = pytest.mark.unit


def test_the_shipped_files_validate() -> None:
    engine._NarrowLadderFile.model_validate(load_data_yaml(engine._NARROW_LADDER_YAML))
    engine._HaiEmpiricalFile.model_validate(load_data_yaml(engine._HAI_EMPIRICAL_YAML))


def test_an_unknown_key_on_an_empirical_drug_fails() -> None:
    data = load_data_yaml(engine._HAI_EMPIRICAL_YAML)
    regimen = data["hai_empirical"]["cauti"]
    bad = {**regimen, "drugs": [{**regimen["drugs"][0], "dosage": "1g"}]}
    with pytest.raises(ValidationError):
        engine._HaiEmpiricalFile.model_validate({**data, "hai_empirical": {**data["hai_empirical"], "cauti": bad}})


def test_an_unknown_frequency_fails() -> None:
    data = load_data_yaml(engine._HAI_EMPIRICAL_YAML)
    regimen = data["hai_empirical"]["cauti"]
    bad = {**regimen, "drugs": [{**regimen["drugs"][0], "frequency": "q36h"}]}
    with pytest.raises(ValidationError):
        engine._HaiEmpiricalFile.model_validate({**data, "hai_empirical": {**data["hai_empirical"], "cauti": bad}})


def test_an_unknown_top_level_key_fails() -> None:
    with pytest.raises(ValidationError):
        engine._NarrowLadderFile.model_validate({**load_data_yaml(engine._NARROW_LADDER_YAML), "ladder": {}})
