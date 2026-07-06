"""FP-YAML-2b Task 3: fail-loud archetype_modifiers validation at protocol load."""

import glob
import os

import pytest

from clinosim.modules.clinical_course.engine import _validate_archetype_modifiers
from clinosim.modules.disease.protocol import load_disease_protocol

pytestmark = pytest.mark.unit

_IDS = [
    os.path.basename(f)[:-5] for f in glob.glob("clinosim/modules/disease/reference_data/*.yaml")
]
_ARCH = {"smooth_recovery", "gradual_deterioration", "treatment_resistant"}


def test_all_real_yamls_validate():
    for d in _IDS:
        load_disease_protocol(d)  # must not raise


def test_effect_key_not_in_archetypes_raises():
    with pytest.raises(ValueError):
        _validate_archetype_modifiers(
            "x",
            [{"condition": "age >= 80", "effect": {"nonexistent_archetype": 0.1}}],
            _ARCH,
        )


def test_unknown_condition_raises():
    with pytest.raises(ValueError):
        _validate_archetype_modifiers(
            "x",
            [{"condition": "made_up_thing", "effect": {"smooth_recovery": 0.1}}],
            _ARCH,
        )


def test_nonnumeric_delta_raises():
    with pytest.raises(ValueError):
        _validate_archetype_modifiers(
            "x",
            [{"condition": "age >= 80", "effect": {"smooth_recovery": "lots"}}],
            _ARCH,
        )
