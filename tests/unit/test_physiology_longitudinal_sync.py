"""The physiology HbA1c noise and clamp match the longitudinal trajectory's.

``physiology/reference_data/chronic_glycemic_thresholds.yaml`` and
``locale/shared/longitudinal/hba1c_trajectory.yaml`` both model the same HbA1c
measurement: the encounter lab emit and the per-year longitudinal trajectory
must draw the same per-measurement noise and clamp to the same physiological
range, or a patient's HbA1c jumps between the two sources.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from clinosim.datafiles import load_data_yaml

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[2] / "clinosim"
_PHYSIOLOGY = _ROOT / "modules/physiology/reference_data/chronic_glycemic_thresholds.yaml"
_TRAJECTORY = _ROOT / "locale/shared/longitudinal/hba1c_trajectory.yaml"


def test_measurement_noise_matches() -> None:
    physiology = load_data_yaml(_PHYSIOLOGY)["hba1c"]
    trajectory = load_data_yaml(_TRAJECTORY)
    assert physiology["measurement_noise_sd"] == trajectory["per_encounter_noise"]["sigma"]


def test_clamp_matches() -> None:
    physiology = load_data_yaml(_PHYSIOLOGY)["hba1c"]
    trajectory = load_data_yaml(_TRAJECTORY)
    assert [physiology["clamp_min"], physiology["clamp_max"]] == trajectory["clamp"]
