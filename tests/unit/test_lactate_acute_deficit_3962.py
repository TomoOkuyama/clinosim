"""Issue #3962: lactate follows the acute perfusion deficit, not the chronic level.

``perfusion_status`` tracks the chronic ``cardiac_function`` of the patient, so
deriving lactate from ``1 - perfusion_status`` gave every patient with a reduced
cardiac reserve a high lactate for the whole stay. The lactate now follows the drop
of perfusion below the patient's chronic baseline (``perfusion_baseline``): a stable
chronic patient has a normal lactate, it rises with an acute deficit, returns to
baseline when the deficit resolves, and still reaches the ceiling at zero perfusion.
"""

from __future__ import annotations

import pytest

from clinosim.modules.physiology._lab_derivation_thresholds import (
    LACTATE_BASELINE_MMOL_L,
    LACTATE_PERFUSION_SCALE,
)
from clinosim.modules.physiology.engine import (
    apply_coupling_rules,
    apply_disease_onset,
    apply_state_delta,
    derive_lab_values,
    initialize_state,
)
from clinosim.types.clinical import PhysiologicalState
from clinosim.types.patient import ChronicCondition, PatientPhysiologicalProfile

pytestmark = pytest.mark.unit

_UPPER_REFERENCE_LIMIT = 2.0
"""Upper reference limit of the emitted lactate reference range (mmol/L)."""


def _lactate(state: PhysiologicalState) -> float:
    return derive_lab_values(state, sex="M", age=60)["Lactate"]


def _chronic(cardiac_reserve: float, conditions: list[ChronicCondition] | None = None) -> PhysiologicalState:
    state = initialize_state(PatientPhysiologicalProfile(cardiac_reserve=cardiac_reserve), conditions or [])
    apply_coupling_rules(state)
    return state


@pytest.mark.parametrize("cardiac_reserve", [1.0, 0.9, 0.8, 0.7, 0.6])
def test_stable_chronic_patient_has_a_normal_lactate(cardiac_reserve: float) -> None:
    state = _chronic(cardiac_reserve)
    assert state.perfusion_status < 1.0 or cardiac_reserve == 1.0
    assert _lactate(state) < _UPPER_REFERENCE_LIMIT
    assert _lactate(state) == pytest.approx(LACTATE_BASELINE_MMOL_L)


def test_chronic_heart_failure_alone_does_not_raise_the_lactate() -> None:
    state = _chronic(0.8, [ChronicCondition(code="I50.9", severity_score=0.8)])
    assert state.perfusion_status < 0.9  # a real chronic reduction
    assert _lactate(state) < _UPPER_REFERENCE_LIMIT


def test_lactate_rises_with_an_acute_deficit_and_returns_when_it_resolves() -> None:
    state = _chronic(0.8)
    chronic = _lactate(state)
    state.volume_status = -0.8  # acute hypovolemia lowers perfusion below the chronic baseline
    apply_coupling_rules(state)
    assert _lactate(state) > chronic + 1.0
    state.volume_status = 0.0  # the deficit resolves
    apply_coupling_rules(state)
    assert _lactate(state) == pytest.approx(chronic)


def test_lactate_ceiling_is_kept_at_zero_perfusion() -> None:
    ceiling = LACTATE_BASELINE_MMOL_L + LACTATE_PERFUSION_SCALE
    for baseline in (1.0, 0.84, 0.6):
        state = PhysiologicalState(perfusion_status=0.0, perfusion_baseline=baseline)
        assert _lactate(state) == pytest.approx(ceiling)


def test_state_without_a_recorded_baseline_keeps_the_previous_derivation() -> None:
    state = PhysiologicalState(perfusion_status=0.5)
    assert _lactate(state) == pytest.approx(LACTATE_BASELINE_MMOL_L + 0.5 * LACTATE_PERFUSION_SCALE)


def test_perfusion_above_the_baseline_is_not_below_the_lactate_baseline() -> None:
    state = PhysiologicalState(perfusion_status=0.9, perfusion_baseline=0.8)
    assert _lactate(state) == pytest.approx(LACTATE_BASELINE_MMOL_L)


# Shock must still give a high lactate.


def test_cardiogenic_shock_in_a_chronic_patient_gives_a_high_lactate() -> None:
    state = _chronic(0.8, [ChronicCondition(code="I25.9", severity_score=0.5)])
    assert _lactate(state) < _UPPER_REFERENCE_LIMIT
    # Acute pump failure (acute MI / acute HF style impact on cardiac function).
    apply_disease_onset(state, "severe", {"severe": {"cardiac_function": -0.5}})
    assert _lactate(state) >= 4.0


def test_septic_shock_with_profound_hypovolemia_gives_a_high_lactate() -> None:
    state = _chronic(0.8)
    apply_disease_onset(
        state, "severe", {"severe": {"inflammation_level": 0.85, "volume_status": -1.0, "perfusion_status": -0.35}}
    )
    assert _lactate(state) >= 4.0


def test_hemorrhagic_shock_gives_a_high_lactate() -> None:
    state = _chronic(0.9)
    apply_disease_onset(state, "severe", {"severe": {"volume_status": -1.0, "anemia_level": 0.5}})
    assert _lactate(state) >= 4.0


def test_perfusion_collapse_after_onset_gives_a_high_lactate() -> None:
    """A perfusion drop applied after the coupling step (terminal or ED course)."""
    state = _chronic(0.8)
    state.perfusion_status = 0.1
    assert _lactate(state) >= 4.0


# An authored perfusion_status delta is an acute deficit that survives the coupling rule.


def test_a_perfusion_delta_survives_the_coupling_rule_and_gives_a_high_lactate() -> None:
    state = _chronic(0.8)
    apply_disease_onset(state, "severe", {"severe": {"perfusion_status": -0.35}})
    apply_coupling_rules(state)
    assert state.perfusion_status == pytest.approx(state.perfusion_baseline - 0.35)
    assert _lactate(state) >= 4.0


def test_the_acute_perfusion_deficit_recovers_with_positive_deltas_and_lactate_returns() -> None:
    state = _chronic(0.8)
    apply_state_delta(state, "perfusion_status", -0.35)
    apply_coupling_rules(state)
    assert _lactate(state) >= 4.0
    for _ in range(3):  # the infection course's recovery deltas
        apply_state_delta(state, "perfusion_status", 0.15)
        apply_coupling_rules(state)
    assert state.perfusion_status == pytest.approx(state.perfusion_baseline)
    assert _lactate(state) == pytest.approx(LACTATE_BASELINE_MMOL_L)


def test_a_recovery_delta_never_lifts_perfusion_above_the_coupled_value() -> None:
    state = _chronic(0.8)
    apply_state_delta(state, "perfusion_status", 0.2)
    apply_coupling_rules(state)
    assert state.perfusion_status == pytest.approx(state.perfusion_baseline)


def test_ed_treatment_response_shrinks_the_acute_deficit() -> None:
    from clinosim.simulator.emergency import ED_TREATMENT_RESPONSE_FACTOR, ed_treatment_response

    state = _chronic(0.8)
    apply_state_delta(state, "perfusion_status", -0.4)
    apply_coupling_rules(state)
    after = ed_treatment_response(state)
    assert after.perfusion_acute_offset == pytest.approx(-0.4 * ED_TREATMENT_RESPONSE_FACTOR)


def test_shock_check_uses_the_drop_below_the_chronic_baseline() -> None:
    from clinosim.simulator.daily_loop import in_shock

    chronic = _chronic(0.4)  # baseline perfusion 0.52: a chronic patient, no acute deficit
    chronic.inflammation_level = 1.0
    assert not in_shock(chronic)
    acute = _chronic(0.4)
    acute.inflammation_level = 1.0
    apply_state_delta(acute, "perfusion_status", -0.3)
    apply_coupling_rules(acute)
    assert in_shock(acute)
    healthy = PhysiologicalState(perfusion_status=0.2)
    assert in_shock(healthy)  # no baseline recorded: the absolute threshold as before


def test_the_acute_deficit_resolves_with_the_infection() -> None:
    from datetime import timedelta

    from clinosim.modules.physiology.engine import update
    from clinosim.types.clinical import StateChangeDirective

    state = _chronic(0.8)
    state.inflammation_level = 0.8
    apply_state_delta(state, "perfusion_status", -0.35)
    apply_coupling_rules(state)
    peak = _lactate(state)
    # The infection course brings the inflammation down; no perfusion delta is authored.
    for _ in range(10):
        update(state, StateChangeDirective(changes={"inflammation_level": -0.1}), timedelta(days=1))
    assert state.inflammation_level == pytest.approx(0.0, abs=1e-9)
    assert peak >= 4.0
    assert _lactate(state) == pytest.approx(LACTATE_BASELINE_MMOL_L)


def test_a_rising_inflammation_does_not_change_the_acute_deficit() -> None:
    from datetime import timedelta

    from clinosim.modules.physiology.engine import update
    from clinosim.types.clinical import StateChangeDirective

    state = _chronic(0.8)
    state.inflammation_level = 0.3
    apply_state_delta(state, "perfusion_status", -0.2)
    update(state, StateChangeDirective(changes={"inflammation_level": 0.2}), timedelta(days=1))
    assert state.perfusion_acute_offset == pytest.approx(-0.2)
