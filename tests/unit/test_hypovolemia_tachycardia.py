"""Volume depletion raises heart rate (compensatory tachycardia, #2054)."""

from __future__ import annotations

from datetime import datetime

import pytest

from clinosim.modules.physiology.engine import derive_vital_signs
from clinosim.types.clinical import PhysiologicalState
from clinosim.types.patient import BaselineVitals

pytestmark = pytest.mark.unit

_TS = datetime(2026, 5, 1, 14, 0)
_BASE = BaselineVitals(
    temperature=36.6, heart_rate=72, systolic_bp=122, diastolic_bp=76, respiratory_rate=14, spo2=98.0
)


def _hr(volume: float) -> int:
    return derive_vital_signs(PhysiologicalState(volume_status=volume), _BASE, _TS)["heart_rate"]


def test_volume_depletion_raises_heart_rate() -> None:
    assert _hr(-0.2) > _hr(0.0)
    assert _hr(-0.4) > _hr(-0.2)
    # moderate depletion (~DKA moderate) lands near 100 from a resting 72
    assert 90 <= _hr(-0.4) <= 105


def test_volume_overload_does_not_raise_heart_rate() -> None:
    assert _hr(0.3) == _hr(0.0)
