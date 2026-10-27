"""Symptom-axis recovery scales with treatment effectiveness (#2097)."""

from __future__ import annotations

import pytest

from clinosim.modules.clinical_course._clinical_course_thresholds import SYMPTOM_AXIS_DAILY_RECOVERY
from clinosim.modules.clinical_course.engine import natural_recovery_directive
from clinosim.types.patient import PatientPhysiologicalProfile

pytestmark = pytest.mark.unit


def _changes(effectiveness: float) -> dict:
    return natural_recovery_directive(
        2, "bacterial_pneumonia", "moderate", PatientPhysiologicalProfile(), treatment_effectiveness=effectiveness
    ).changes


def test_full_effectiveness_keeps_the_recovery_rate() -> None:
    changes = _changes(1.0)
    for axis, rate in SYMPTOM_AXIS_DAILY_RECOVERY.items():
        assert changes[axis] == pytest.approx(-rate)


def test_ineffective_treatment_slows_but_does_not_stop_recovery() -> None:
    full, none = _changes(1.0), _changes(0.0)
    for axis in SYMPTOM_AXIS_DAILY_RECOVERY:
        assert full[axis] < none[axis] < 0
