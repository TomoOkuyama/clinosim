"""Barthel recovery follows the clinical state and the discharge day is assessed (Issue #3647)."""

from __future__ import annotations

from datetime import datetime

import numpy as np
import pytest

from clinosim.seeding import adl_discharge_seed
from clinosim.simulator._adl_thresholds import ADL_MAX_GAIN_PER_ASSESSMENT
from clinosim.simulator.vitals_pipeline import _barthel_expected, _generate_adl_assessment
from clinosim.types.clinical import PhysiologicalState
from clinosim.types.patient import PatientProfile

pytestmark = pytest.mark.unit

_ADMIT = datetime(2026, 7, 19, 10)
_PATIENT = PatientProfile(patient_id="P3647", sex="F", age=76)


def _febrile(**over: float) -> PhysiologicalState:
    return PhysiologicalState(inflammation_level=0.8, oxygenation_impairment=0.5, perfusion_status=0.8, **over)


def test_unchanged_febrile_state_gives_the_same_expected_score_a_week_apart() -> None:
    state = _febrile()
    first = _barthel_expected(state, _PATIENT, 0)[0]
    later = _barthel_expected(state, _PATIENT, 7)[0]
    assert abs(later - first) <= 5


def test_later_assessment_keeps_the_acute_and_renal_penalties_while_acute() -> None:
    state = _febrile(renal_function=0.6)
    healthy_kidney = _barthel_expected(_febrile(), _PATIENT, 7)[0]
    assert _barthel_expected(state, _PATIENT, 7)[0] < healthy_kidney


def test_recovery_follows_the_resolved_state() -> None:
    acute = _barthel_expected(_febrile(), _PATIENT, 7)[0]
    resolved = _barthel_expected(PhysiologicalState(), _PATIENT, 14)[0]
    assert resolved - acute >= 20  # the recovery comes from the resolved state


def test_no_time_based_recovery_without_a_state_change() -> None:
    state = _febrile()
    assert _barthel_expected(state, _PATIENT, 21)[0] == _barthel_expected(state, _PATIENT, 7)[0]


def test_gain_between_assessments_is_capped() -> None:
    for seed in range(30):
        adl = _generate_adl_assessment(
            PhysiologicalState(), _PATIENT, 7, _ADMIT, np.random.default_rng(seed), previous_score=30
        )
        assert adl is not None
        assert adl.barthel_score - 30 <= ADL_MAX_GAIN_PER_ASSESSMENT


def test_day_zero_is_unchanged_by_the_new_arguments() -> None:
    a = _generate_adl_assessment(_febrile(), _PATIENT, 0, _ADMIT, np.random.default_rng(3))
    b = _generate_adl_assessment(_febrile(), _PATIENT, 0, _ADMIT, np.random.default_rng(3), previous_score=None)
    assert a is not None and b is not None and a.barthel_score == b.barthel_score


def test_discharge_day_assessment_is_made_off_the_weekly_schedule() -> None:
    rng = np.random.default_rng(adl_discharge_seed("ENC-1"))
    assert _generate_adl_assessment(_febrile(), _PATIENT, 5, _ADMIT, rng) is None
    adl = _generate_adl_assessment(
        _febrile(), _PATIENT, 5, _ADMIT, np.random.default_rng(adl_discharge_seed("ENC-1")), at_discharge=True
    )
    assert adl is not None and adl.date == datetime(2026, 7, 24).date()


def test_discharge_seed_is_stable_and_per_encounter() -> None:
    assert adl_discharge_seed("ENC-1") == adl_discharge_seed("ENC-1") != adl_discharge_seed("ENC-2")
