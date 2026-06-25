"""Integration tests for Phase 3a HAI WBC + CRP forward-delta lab lift.

Post PR-90 xhigh review hardening:
  - All HAIEvent fixtures use the canonical lowercase ``hai_type`` strings
    from ``modules.hai.HAI_TYPES`` (the test that previously passed with
    UPPERCASE hai_type was masking the production no-op bug).
  - state_history fixtures include the admission state at index 0 and the
    post-day-N state at index N+1, matching the daily-loop layout.
  - lab_results fixtures are backed by Order objects with ordered_datetime
    so the WBC circadian draw-hour path is exercised.
  - Tests verify both obs.value and the recomputed obs.flag.
"""
from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from clinosim.modules.hai import HAI_TYPES
from clinosim.modules.hai.lab_lift import (
    _hai_lift_delta,
    apply_hai_lab_lift,
    load_hai_lab_lift_config,
)
from clinosim.types.clinical import PhysiologicalState
from clinosim.types.encounter import Order, OrderResult, OrderType
from clinosim.types.hai import HAIEvent


def _state(infl: float) -> PhysiologicalState:
    return PhysiologicalState(inflammation_level=infl)


def _hai_event(
    encounter_id: str = "enc-1",
    hai_type: str = "clabsi",
    onset_date: str = "2026-01-10",
    hai_id: str = "hai-1",
) -> HAIEvent:
    assert hai_type in HAI_TYPES, (
        f"test fixture uses unknown hai_type {hai_type!r}; "
        "tests must use HAI_TYPES to catch case-mismatch bugs"
    )
    return HAIEvent(
        hai_id=hai_id,
        encounter_id=encounter_id,
        hai_type=hai_type,
        source_device_id="dev-1",
        icd10_code="T80.211A",
        snomed_code="736442006",
        onset_date=onset_date,
        organism_snomed="3092008",
        culture_specimen_id="spec-1",
    )


def _patient() -> SimpleNamespace:
    return SimpleNamespace(sex="M", age=60, patient_id="P1")


def _encounter() -> SimpleNamespace:
    return SimpleNamespace(encounter_id="enc-1")


def _ordered_obs(
    lab_name: str,
    result_dt: datetime,
    value: float,
    draw_hour: int = 6,
):
    """Build an OrderResult plus its parent Order so the lift code's
    result_to_order map can resolve the draw hour."""
    obs = OrderResult(
        result_datetime=result_dt,
        performed_by="lab",
        lab_name=lab_name,
        value=value,
    )
    order = Order(
        order_id=f"ord-{lab_name}-{result_dt.isoformat()}",
        patient_id="P1",
        order_type=OrderType.LAB,
        display_name=lab_name,
        ordered_datetime=datetime(
            result_dt.year, result_dt.month, result_dt.day, draw_hour, 30,
        ),
    )
    order.result = obs
    return obs, order


def _record(events, lab_results, orders, encounter_id="enc-1"):
    return SimpleNamespace(
        patient=_patient(),
        extensions={"hai": events} if events else {},
        lab_results=lab_results,
        orders=orders,
    )


def _build_state_history(infl_per_day: list[float]) -> list[PhysiologicalState]:
    """Build a state_history whose index 0 is the admission state and
    whose index N+1 is the post-day-N state."""
    history = [PhysiologicalState(inflammation_level=infl_per_day[0])]
    for i in infl_per_day:
        history.append(PhysiologicalState(inflammation_level=i))
    return history


@pytest.mark.integration
def test_no_hai_events_no_changes():
    """Empty extensions — apply_hai_lab_lift is a no-op."""
    obs, order = _ordered_obs("WBC", datetime(2026, 1, 12, 8), 11800.0)
    record = _record(None, [obs], [order])
    n = apply_hai_lab_lift(
        record, _encounter(), _build_state_history([0.4] * 5),
        datetime(2026, 1, 8, 0),
    )
    assert n == 0
    assert obs.value == 11800.0


@pytest.mark.integration
def test_clabsi_full_lift_at_day_2_uses_closed_form_and_draw_hour():
    """Day 4 obs (2 days past onset) → full ramp.

    The closed-form delta should be:
      WBC pre-circadian (eff=0.75) - WBC pre-circadian (infl=0.4)
        = (7000 + 0.75 * 12000) - (7000 + 0.4 * 12000)
        = 16000 - 11800 = 4200
      circadian(6) = 1.0 + 0.10 * sin((6-4) * pi / 12) = 1.05
      delta_WBC = 4200 * 1.05 = 4410
    CRP: 400 * (0.75^3 - 0.4^3) = 400 * (0.421875 - 0.064) = 143.15
    """
    admission = datetime(2026, 1, 8, 0)
    state_history = _build_state_history([0.4] * 8)
    wbc_obs, wbc_order = _ordered_obs(
        "WBC", datetime(2026, 1, 12, 8), 11760.0, draw_hour=6,
    )  # 11800 * 1.05 circadian (close to integer)
    crp_obs, crp_order = _ordered_obs(
        "CRP", datetime(2026, 1, 12, 8), 25.9,
    )
    record = _record(
        [_hai_event(onset_date="2026-01-10")], [wbc_obs, crp_obs], [wbc_order, crp_order],
    )

    n = apply_hai_lab_lift(record, _encounter(), state_history, admission)
    assert n == 2
    assert wbc_obs.value == pytest.approx(11760 + 4200 * 1.05, abs=1.0)
    assert crp_obs.value == pytest.approx(
        25.9 + 400 * (0.75**3 - 0.4**3), abs=0.5,
    )
    # Flag recomputed: lifted CRP ~169 mg/L is high (default ref 0-3),
    # lifted WBC ~16100 is high (default ref ~4500-11000).
    assert crp_obs.flag in ("H", "critical")
    assert wbc_obs.flag in ("H", "critical")


@pytest.mark.integration
def test_pre_onset_observation_unchanged():
    """day 1 obs (before onset_date=day 2) is NOT lifted."""
    admission = datetime(2026, 1, 8, 0)
    obs, order = _ordered_obs(
        "WBC", datetime(2026, 1, 9, 8), 11800.0,
    )  # day 1, onset 2026-01-10 → pre-onset
    record = _record(
        [_hai_event(onset_date="2026-01-10")], [obs], [order],
    )
    apply_hai_lab_lift(
        record, _encounter(), _build_state_history([0.4] * 5), admission,
    )
    assert obs.value == 11800.0


@pytest.mark.integration
def test_ramp_at_day_1_is_half_lift():
    """day 1 past onset → ramp_factor = 1/2 = 0.5 → effective_lift = 0.175."""
    admission = datetime(2026, 1, 8, 0)
    state_history = _build_state_history([0.4] * 5)
    obs, order = _ordered_obs(
        "CRP", datetime(2026, 1, 11, 8), 25.9,
    )
    record = _record(
        [_hai_event(onset_date="2026-01-10")], [obs], [order],
    )
    apply_hai_lab_lift(record, _encounter(), state_history, admission)
    expected_delta = 400 * ((0.4 + 0.175) ** 3 - 0.4 ** 3)
    assert obs.value == pytest.approx(25.9 + expected_delta, abs=0.5)


@pytest.mark.integration
def test_encounter_mismatch_no_lift():
    """HAI event for a different encounter does not lift this encounter's labs."""
    admission = datetime(2026, 1, 8, 0)
    obs, order = _ordered_obs("CRP", datetime(2026, 1, 12, 8), 25.9)
    record = _record(
        [_hai_event(encounter_id="OTHER")], [obs], [order],
    )
    apply_hai_lab_lift(
        record, _encounter(), _build_state_history([0.4] * 5), admission,
    )
    assert obs.value == 25.9


@pytest.mark.integration
def test_non_wbc_crp_observation_untouched():
    """Phase 3a scope guard: BUN / K / etc. not modified."""
    admission = datetime(2026, 1, 8, 0)
    obs, order = _ordered_obs("BUN", datetime(2026, 1, 12, 8), 15.0)
    record = _record(
        [_hai_event()], [obs], [order],
    )
    apply_hai_lab_lift(
        record, _encounter(), _build_state_history([0.4] * 5), admission,
    )
    assert obs.value == 15.0


@pytest.mark.integration
def test_multi_event_takes_max_not_sum():
    """CLABSI 0.35 + CAUTI 0.20 same day → max 0.35, not 0.55."""
    admission = datetime(2026, 1, 8, 0)
    state_history = _build_state_history([0.4] * 8)
    obs, order = _ordered_obs("CRP", datetime(2026, 1, 12, 8), 25.9)
    events = [
        _hai_event(hai_type="clabsi", onset_date="2026-01-10", hai_id="h1"),
        _hai_event(hai_type="cauti", onset_date="2026-01-10", hai_id="h2"),
    ]
    record = _record(events, [obs], [order])
    apply_hai_lab_lift(record, _encounter(), state_history, admission)
    # Expected = baseline + delta_for_max_lift_0.35 (NOT delta_for_0.55)
    expected_delta_max = 400 * (0.75 ** 3 - 0.4 ** 3)
    expected_delta_sum = 400 * (0.95 ** 3 - 0.4 ** 3)
    assert obs.value == pytest.approx(25.9 + expected_delta_max, abs=0.5)
    assert obs.value < 25.9 + expected_delta_sum  # NOT additive


@pytest.mark.integration
def test_state_history_index_is_post_day_state():
    """day_index N uses state_history[N+1] = post-day-N state."""
    admission = datetime(2026, 1, 8, 0)
    # admission infl = 0.0, day-0 post = 0.4, day-1 post = 0.6, day-2 post = 0.8
    state_history = [
        PhysiologicalState(inflammation_level=v)
        for v in (0.0, 0.4, 0.6, 0.8, 0.8, 0.8)
    ]
    # day 2 obs → state_history[3] = 0.8 should be used
    obs, order = _ordered_obs("CRP", datetime(2026, 1, 10, 8), 0.3 + 400 * 0.8 ** 3)
    record = _record(
        [_hai_event(onset_date="2026-01-08")], [obs], [order],
    )
    apply_hai_lab_lift(record, _encounter(), state_history, admission)
    # Lift on infl=0.8 with 0.35 lift → eff_infl=1.0 → CRP = 0.3 + 400 = 400.3
    # delta = 400 * (1.0^3 - 0.8^3) = 400 * 0.488 = 195.2
    assert obs.value == pytest.approx(0.3 + 400 * 0.8 ** 3 + 195.2, abs=1.0)


@pytest.mark.integration
def test_wbc_uses_order_draw_hour_not_result_hour():
    """obs.result_datetime.hour=10 (post-turnaround), order.ordered_datetime.hour=6
    (actual draw); circadian factor differs (10 → 1.087, 6 → 1.05). The lift
    must use the draw hour."""
    admission = datetime(2026, 1, 8, 0)
    state_history = _build_state_history([0.4] * 5)
    result_dt = datetime(2026, 1, 10, 10)  # result at 10 AM
    obs, order = _ordered_obs(
        "WBC", result_dt, 11760.0, draw_hour=6,
    )  # but draw at 6 AM
    record = _record(
        [_hai_event(onset_date="2026-01-08")], [obs], [order],
    )
    apply_hai_lab_lift(record, _encounter(), state_history, admission)
    # delta = 4200 * circadian(6) = 4200 * 1.05 = 4410
    expected_delta = 4200 * 1.05
    assert obs.value == pytest.approx(11760 + expected_delta, abs=1.0)


@pytest.mark.integration
def test_wbc_is_rounded_to_integer_precision():
    """PRECISION['WBC'] = 0 → lifted WBC must not carry decimals."""
    admission = datetime(2026, 1, 8, 0)
    state_history = _build_state_history([0.4] * 5)
    obs, order = _ordered_obs("WBC", datetime(2026, 1, 10, 8), 11760.0, draw_hour=6)
    record = _record(
        [_hai_event(onset_date="2026-01-08")], [obs], [order],
    )
    apply_hai_lab_lift(record, _encounter(), state_history, admission)
    assert obs.value == int(obs.value), (
        f"WBC was {obs.value} — PRECISION['WBC']=0 requires integer"
    )


@pytest.mark.integration
def test_obs_flag_recomputed_after_lift():
    """obs.flag must reflect the lifted value, not the pre-lift baseline."""
    admission = datetime(2026, 1, 8, 0)
    state_history = _build_state_history([0.4] * 5)
    crp_obs, crp_order = _ordered_obs("CRP", datetime(2026, 1, 10, 8), 5.0)
    crp_obs.flag = "N"  # pretend daily loop computed a normal flag
    record = _record(
        [_hai_event(onset_date="2026-01-08")], [crp_obs], [crp_order],
    )
    apply_hai_lab_lift(record, _encounter(), state_history, admission)
    # Lifted CRP ~143 mg/L is high
    assert crp_obs.flag in ("H", "critical")


@pytest.mark.integration
def test_load_config_rejects_unknown_hai_type():
    """Regression guard for the case-mismatch class of bug — YAML must use
    canonical HAI_TYPES; an UPPERCASE key would have raised here at import
    time instead of silently no-op'ing every lookup."""
    from clinosim.modules.hai import HAI_TYPES as _types
    _, lift_table = load_hai_lab_lift_config()
    for key in lift_table:
        assert key in _types, (
            f"hai_lab_lift.yaml key {key!r} not in HAI_TYPES {_types}"
        )


@pytest.mark.integration
def test_closed_form_matches_derive_lab_values_double_call():
    """The closed-form delta must equal the difference of two
    ``derive_lab_values`` invocations on the same state — this is the
    invariant the more-expensive implementation it replaces was upholding."""
    from clinosim.modules.physiology.engine import derive_lab_values

    state = PhysiologicalState(inflammation_level=0.4)
    for draw_hour in (4, 6, 10, 16):
        baseline = derive_lab_values(state, sex="M", age=60, hour=draw_hour)
        lifted = derive_lab_values(
            state, sex="M", age=60, hour=draw_hour, hai_inflammation_lift=0.35,
        )
        assert _hai_lift_delta(state, "CRP", 0.35, draw_hour) == pytest.approx(
            lifted["CRP"] - baseline["CRP"], abs=0.05,
        )
        assert _hai_lift_delta(state, "WBC", 0.35, draw_hour) == pytest.approx(
            lifted["WBC"] - baseline["WBC"], abs=1.0,
        )
