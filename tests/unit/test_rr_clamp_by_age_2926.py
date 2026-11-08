"""Respiratory-rate ceiling by age (Issue #2926).

The adult ceiling of 45 /min sits below the healthy 99th centile of infants
(Fleming et al. 2011), so a distressed infant must be able to breathe faster;
adults and children from 12 years keep 45. Only the clamp bound moves: the
noise draws are the same.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from clinosim.determinism import default_rng
from clinosim.modules.observation.pediatric_ranges import pediatric_vital_max, pediatric_vital_range
from clinosim.modules.physiology._vital_signs_thresholds import RR_CLAMP_MAX
from clinosim.modules.physiology.engine import derive_observed_vitals, derive_vital_signs, rr_clamp_max
from clinosim.types.clinical import PhysiologicalState
from clinosim.types.patient import BaselineVitals

pytestmark = pytest.mark.unit

_TS = datetime(2025, 1, 15, 10, 0, 0)


def _distressed() -> PhysiologicalState:
    """Severe pneumonia / sepsis: fever, hypoxaemia, sympathetic drive, acidosis."""
    return PhysiologicalState(
        patient_id="t",
        inflammation_level=0.9,
        oxygenation_impairment=0.9,
        sympathetic_activation=0.9,
        ph_status=-1.0,
    )


def _infant_baseline() -> BaselineVitals:
    return BaselineVitals(temperature=36.8, heart_rate=140, systolic_bp=85, diastolic_bp=50, respiratory_rate=42)


@pytest.mark.parametrize(
    ("age_months", "expected"),
    [(0, 80.0), (11, 80.0), (12, 60.0), (71, 60.0), (72, 50.0), (143, 50.0), (144, RR_CLAMP_MAX), (600, RR_CLAMP_MAX)],
)
def test_ceiling_by_age(age_months: int, expected: float) -> None:
    assert rr_clamp_max(age_months) == expected


def test_unknown_age_keeps_adult_ceiling() -> None:
    assert rr_clamp_max(None) == RR_CLAMP_MAX


def test_ceiling_above_normal_99th_centile() -> None:
    """Every child's normal range stays reachable under the ceiling."""
    for months in range(0, 144):
        band = pediatric_vital_range("respiratory_rate", months)
        ceiling = pediatric_vital_max("respiratory_rate", months)
        assert band is not None and ceiling is not None
        assert ceiling > band.high


def test_distressed_infant_exceeds_45() -> None:
    rr = derive_vital_signs(_distressed(), _infant_baseline(), _TS, age_months=4)["respiratory_rate"]
    assert 45 < rr <= 80


def test_distressed_adult_capped_at_45() -> None:
    adult = derive_vital_signs(_distressed(), BaselineVitals(), _TS, age_months=40 * 12)["respiratory_rate"]
    assert adult == RR_CLAMP_MAX
    # Same patient through the infant baseline but an adult age: still capped.
    assert derive_vital_signs(_distressed(), _infant_baseline(), _TS, age_months=None)["respiratory_rate"] == 45


def test_observed_infant_exceeds_45_adult_capped() -> None:
    infant = derive_observed_vitals(_distressed(), _infant_baseline(), _TS, default_rng(7), age_months=4)
    adult = derive_observed_vitals(_distressed(), _infant_baseline(), _TS, default_rng(7), age_months=40 * 12)
    assert infant["respiratory_rate"] > 45
    assert adult["respiratory_rate"] <= RR_CLAMP_MAX


def test_same_draws_whatever_the_age() -> None:
    """Only the bound moves: the RNG is advanced identically and the other
    vitals are unchanged."""
    rng_infant, rng_adult = default_rng(11), default_rng(11)
    infant = derive_observed_vitals(_distressed(), _infant_baseline(), _TS, rng_infant, age_months=4)
    adult = derive_observed_vitals(_distressed(), _infant_baseline(), _TS, rng_adult, age_months=None)
    assert rng_infant.random() == rng_adult.random()
    for key in ("temperature", "heart_rate", "systolic_bp", "diastolic_bp", "spo2"):
        assert infant[key] == adult[key]
