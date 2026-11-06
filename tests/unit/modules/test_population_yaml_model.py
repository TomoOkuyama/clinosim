"""anthropometric_reference.yaml is validated by an extra="forbid" Pydantic model."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from clinosim.modules.population._pediatric_anthropometry import _AnthropometricReference

pytestmark = pytest.mark.unit

_PATH = Path(__file__).resolve().parents[3] / "clinosim/modules/population/reference_data/anthropometric_reference.yaml"


def _data() -> dict:
    data = yaml.safe_load(_PATH.read_text(encoding="utf-8"))
    data.pop("metadata", None)
    return data


def test_the_shipped_file_validates() -> None:
    _AnthropometricReference.model_validate(_data())


def _fails(mutate) -> None:
    data = _data()
    mutate(data)
    with pytest.raises(ValidationError):
        _AnthropometricReference.model_validate(data)


def test_a_missing_pediatric_age_fails() -> None:
    _fails(lambda d: d["pediatric_growth"]["JP"]["female"].pop(9))


def test_a_median_outside_the_clamps_fails() -> None:
    _fails(lambda d: d["pediatric_growth"]["US"]["male"][5].update(height=300.0))


def test_an_inverted_clamp_fails() -> None:
    _fails(lambda d: d["clamps"]["bmi"].update(min=70.0))


def test_a_misspelled_key_fails() -> None:
    _fails(lambda d: d["pediatric_sampling"].update(bmi_sdd=1.0))


def test_a_head_circumference_is_required_in_early_childhood() -> None:
    _fails(lambda d: d["pediatric_growth"]["US"]["female"][2].pop("head_circumference"))
