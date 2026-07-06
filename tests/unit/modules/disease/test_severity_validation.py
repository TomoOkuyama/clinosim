"""FP-SEV-MODEL Task 4: fail-loud severity-block validation at protocol load."""

import glob
import os

import pytest

from clinosim.modules.disease.protocol import load_disease_protocol
from clinosim.modules.disease.severity import _validate_severity_block

pytestmark = pytest.mark.unit

_IDS = [
    os.path.basename(f)[:-5] for f in glob.glob("clinosim/modules/disease/reference_data/*.yaml")
]


def test_all_real_disease_severity_blocks_valid():
    for d in _IDS:
        load_disease_protocol(d)  # must not raise


def test_bad_distribution_raises():
    with pytest.raises(ValueError):
        _validate_severity_block(
            "x", {"distribution": {"mild": 0.0, "moderate": 0.0, "severe": 0.0}}, None
        )


def test_missing_category_raises():
    with pytest.raises(ValueError):
        _validate_severity_block("x", {"distribution": {"mild": 0.5, "moderate": 0.5}}, None)


def test_unknown_modifier_condition_raises():
    with pytest.raises(ValueError):
        _validate_severity_block(
            "x",
            {
                "distribution": {"mild": 0.3, "moderate": 0.4, "severe": 0.3},
                "modifiers": [{"condition": "totally_made_up", "severe_multiplier": 2.0}],
            },
            None,
        )


def test_bad_minimum_raises():
    with pytest.raises(ValueError):
        _validate_severity_block(
            "x", {"distribution": {"mild": 0.3, "moderate": 0.4, "severe": 0.3}}, "critical"
        )


def test_nonpositive_multiplier_raises():
    with pytest.raises(ValueError):
        _validate_severity_block(
            "x",
            {
                "distribution": {"mild": 0.3, "moderate": 0.4, "severe": 0.3},
                "modifiers": [{"condition": "age_over_75", "severe_multiplier": 0.0}],
            },
            None,
        )
