"""The llm_service reference YAML is validated by extra="forbid" Pydantic models."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from clinosim.modules.llm_service.engine import _TaskCategoriesFile, _TaskLoincsFile

pytestmark = pytest.mark.unit

_REF = Path(__file__).resolve().parents[3] / "clinosim/modules/llm_service/reference_data"


def _data(name: str) -> dict:
    data = yaml.safe_load((_REF / f"{name}.yaml").read_text(encoding="utf-8"))
    data.pop("metadata", None)
    return data


def test_the_shipped_files_validate() -> None:
    _TaskCategoriesFile.model_validate(_data("task_categories"))
    _TaskLoincsFile.model_validate(_data("task_loincs"))


def test_an_unknown_category_fails() -> None:
    data = _data("task_categories")
    data["categories"]["admission_hp"] = "narative"
    with pytest.raises(ValidationError):
        _TaskCategoriesFile.model_validate(data)


def test_a_misspelled_top_level_key_fails() -> None:
    with pytest.raises(ValidationError):
        _TaskCategoriesFile.model_validate({"categorys": _data("task_categories")["categories"]})


def test_an_unregistered_loinc_fails() -> None:
    with pytest.raises(ValidationError):
        _TaskLoincsFile.model_validate({"loincs": {"death_summary": "00000-0"}})
