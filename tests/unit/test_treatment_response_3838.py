"""A deteriorating course resolves its fever once the escalated treatment has had time to act (Issue #3838)."""

from __future__ import annotations

import pytest

from clinosim.modules.clinical_course.engine import get_daily_directive, treatment_response_rules
from clinosim.types.patient import PatientPhysiologicalProfile

PROFILE = PatientPhysiologicalProfile(immune_reactivity=0.5, treatment_sensitivity=1.0)


def _archetypes(tail: float = 0.02, treatment_days: tuple[int, ...] = (3,)) -> dict:
    return {
        "gradual_deterioration": {
            "trajectory": {"inflammation_level": {0: 0.10, 5: 0.05, 14: tail}},
            "treatment_modifications": {f"day_{d}": {"stop": ["x"]} for d in treatment_days},
        }
    }


def _delta(day: int, archetypes: dict, name: str = "gradual_deterioration", age: int = 40) -> float:
    d = get_daily_directive(name, day, PROFILE, protocol_archetypes=archetypes, age=age, rng=None)
    return d.changes["inflammation_level"]


def test_rules_load_and_name_the_archetypes() -> None:
    rules = treatment_response_rules()
    assert rules.response_delay_days >= 1
    assert rules.resolution_inflammation_delta < 0
    assert {"gradual_deterioration", "treatment_resistant"} <= set(rules.archetypes)


def test_course_keeps_deteriorating_until_the_treatment_has_acted() -> None:
    rules = treatment_response_rules()
    arch = _archetypes()
    last_change = 3
    for day in range(0, last_change + rules.response_delay_days):
        assert _delta(day, arch) > 0, day


def test_inflammation_then_falls_every_day_however_open_the_authored_tail_is() -> None:
    rules = treatment_response_rules()
    arch = _archetypes(tail=0.05)  # an authored tail that keeps rising for ever
    first = 3 + rules.response_delay_days
    for day in (first, first + 5, 40, 90):
        assert _delta(day, arch) <= rules.resolution_inflammation_delta + 1e-9, day


def test_an_authored_recovery_faster_than_the_floor_is_kept() -> None:
    arch = {"gradual_deterioration": {"trajectory": {"inflammation_level": {0: -0.2}}}}
    assert _delta(30, arch) == -0.2


def test_archetypes_without_treatment_changes_resolve_after_their_last_authored_day() -> None:
    rules = treatment_response_rules()
    arch = {"gradual_deterioration": {"trajectory": {"inflammation_level": {0: 0.04, 7: 0.02}}}}
    assert _delta(7 + rules.response_delay_days - 1, arch) > 0
    assert _delta(7 + rules.response_delay_days, arch) <= rules.resolution_inflammation_delta + 1e-9


def test_other_archetypes_are_untouched() -> None:
    arch = {"smooth_recovery": {"trajectory": {"inflammation_level": {0: 0.01}}}}
    assert _delta(60, arch, name="smooth_recovery") == 0.01


def test_a_complication_inflammation_push_is_held_then_fades_at_the_resolution_rate() -> None:
    from clinosim.simulator.sustained_complication import advance_holds, inflammation_push_hold
    from clinosim.types.clinical import PhysiologicalState

    rules = treatment_response_rules()
    state = PhysiologicalState(inflammation_level=0.3)
    holds = {("renal_abscess", "inflammation_level"): inflammation_push_hold(0.2)}
    advance_holds(state, holds)
    assert state.inflammation_level == pytest.approx(0.5)
    for _ in range(rules.response_delay_days - 1):  # held in full until the treatment has acted
        advance_holds(state, holds)
        assert state.inflammation_level == pytest.approx(0.5)
    advance_holds(state, holds)
    assert state.inflammation_level == pytest.approx(0.5 + rules.resolution_inflammation_delta)
    for _ in range(10):
        advance_holds(state, holds)
    assert state.inflammation_level == pytest.approx(0.3)  # back to what the course had without it
    assert holds == {}
