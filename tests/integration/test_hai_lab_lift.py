"""Integration tests for Phase 3a HAI WBC + CRP forward-delta lab lift.

Two layers:
  1. Forward-delta correctness — call apply_hai_lab_lift on a hand-built
     record + state_history and assert that obs.value moved by exactly the
     formula-derived delta (not reverse-engineered).
  2. End-to-end clinical sanity — run a small US simulation with
     hai+device enabled and assert HAI cohort WBC + CRP exceed the non-HAI
     inpatient baseline (skip-if-rare-event).
"""
from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from clinosim.modules.hai.lab_lift import apply_hai_lab_lift
from clinosim.modules.physiology.engine import derive_lab_values
from clinosim.types.clinical import PhysiologicalState
from clinosim.types.encounter import OrderResult
from clinosim.types.hai import HAIEvent


def _state(infl: float) -> PhysiologicalState:
    return PhysiologicalState(inflammation_level=infl)


def _hai_event(
    encounter_id: str = "enc-1",
    hai_type: str = "CLABSI",
    onset_date: str = "2026-01-10",
) -> HAIEvent:
    return HAIEvent(
        hai_id="hai-1",
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


def _obs(name: str, dt: datetime, val: float) -> OrderResult:
    return OrderResult(
        result_datetime=dt, performed_by="lab",
        lab_name=name, value=val,
    )


@pytest.mark.integration
def test_no_hai_events_no_changes():
    """Empty extensions — apply_hai_lab_lift is a no-op."""
    obs = _obs("WBC", datetime(2026, 1, 12, 6), 11800.0)
    record = SimpleNamespace(
        patient=_patient(), extensions={}, lab_results=[obs],
    )
    n = apply_hai_lab_lift(
        record, _encounter(), [_state(0.4)] * 5,
        datetime(2026, 1, 8, 0),
    )
    assert n == 0
    assert obs.value == 11800.0


@pytest.mark.integration
def test_clabsi_full_lift_at_day_2():
    """CLABSI lift 0.35 * ramp 1.0; baseline infl=0.4 → delta is the
    forward formula difference, not a reverse-engineered approximation."""
    admission = datetime(2026, 1, 8, 0)
    onset = "2026-01-10"
    obs_dt = datetime(2026, 1, 12, 4)  # day 4, day_since_onset=2 → full ramp
    state_for_day = _state(0.4)
    state_history = [state_for_day for _ in range(8)]

    # Compute expected delta from the same formula path:
    baseline = derive_lab_values(state_for_day, sex="M", age=60, hour=4)
    lifted = derive_lab_values(
        state_for_day, sex="M", age=60, hour=4, hai_inflammation_lift=0.35,
    )
    expected_wbc_delta = lifted["WBC"] - baseline["WBC"]
    expected_crp_delta = lifted["CRP"] - baseline["CRP"]

    # Seed observations with the un-lifted values (simulating a daily-loop
    # output without HAI). Use round(v, 1) to mirror the lift's rounding.
    wbc_obs = _obs("WBC", obs_dt, round(baseline["WBC"], 1))
    crp_obs = _obs("CRP", obs_dt, round(baseline["CRP"], 1))
    record = SimpleNamespace(
        patient=_patient(),
        extensions={"hai": [_hai_event(onset_date=onset)]},
        lab_results=[wbc_obs, crp_obs],
    )
    n = apply_hai_lab_lift(record, _encounter(), state_history, admission)
    assert n == 2
    assert wbc_obs.value == pytest.approx(
        round(baseline["WBC"], 1) + expected_wbc_delta, abs=0.2,
    )
    assert crp_obs.value == pytest.approx(
        round(baseline["CRP"], 1) + expected_crp_delta, abs=0.2,
    )


@pytest.mark.integration
def test_pre_onset_observation_unchanged():
    """day 1 obs (before onset_date=day 2) is NOT lifted."""
    admission = datetime(2026, 1, 8, 0)
    obs_dt = datetime(2026, 1, 9, 4)   # day 1 — pre-onset
    obs = _obs("WBC", obs_dt, 11800.0)
    record = SimpleNamespace(
        patient=_patient(),
        extensions={"hai": [_hai_event(onset_date="2026-01-10")]},
        lab_results=[obs],
    )
    apply_hai_lab_lift(
        record, _encounter(), [_state(0.4)] * 5, admission,
    )
    assert obs.value == 11800.0


@pytest.mark.integration
def test_ramp_at_day_1_is_half_lift():
    """day 1 (1 day past onset) → ramp_factor = 1/2 = 0.5."""
    admission = datetime(2026, 1, 8, 0)
    obs_dt = datetime(2026, 1, 11, 4)  # day 3 calendar; 1 day past onset 2026-01-10
    state_for_day = _state(0.4)
    state_history = [state_for_day for _ in range(5)]

    baseline = derive_lab_values(state_for_day, sex="M", age=60, hour=4)
    lifted_half = derive_lab_values(
        state_for_day, sex="M", age=60, hour=4,
        hai_inflammation_lift=0.175,  # 0.35 * 0.5
    )
    expected_delta = lifted_half["CRP"] - baseline["CRP"]

    crp_obs = _obs("CRP", obs_dt, round(baseline["CRP"], 1))
    record = SimpleNamespace(
        patient=_patient(),
        extensions={"hai": [_hai_event(onset_date="2026-01-10")]},
        lab_results=[crp_obs],
    )
    apply_hai_lab_lift(record, _encounter(), state_history, admission)
    assert crp_obs.value == pytest.approx(
        round(baseline["CRP"], 1) + expected_delta, abs=0.2,
    )


@pytest.mark.integration
def test_encounter_mismatch_no_lift():
    """HAI event for a different encounter does not lift this encounter's labs."""
    admission = datetime(2026, 1, 8, 0)
    obs = _obs("CRP", datetime(2026, 1, 12, 4), 26.0)
    record = SimpleNamespace(
        patient=_patient(),
        extensions={"hai": [_hai_event(encounter_id="OTHER")]},
        lab_results=[obs],
    )
    apply_hai_lab_lift(record, _encounter(), [_state(0.4)] * 5, admission)
    assert obs.value == 26.0


@pytest.mark.integration
def test_non_wbc_crp_observation_untouched():
    """Phase 3a scope guard: BUN / K / etc. not modified."""
    admission = datetime(2026, 1, 8, 0)
    bun_obs = _obs("BUN", datetime(2026, 1, 12, 4), 15.0)
    record = SimpleNamespace(
        patient=_patient(),
        extensions={"hai": [_hai_event()]},
        lab_results=[bun_obs],
    )
    apply_hai_lab_lift(record, _encounter(), [_state(0.4)] * 5, admission)
    assert bun_obs.value == 15.0


@pytest.mark.integration
def test_cauti_lower_lift_than_clabsi():
    """CAUTI 0.20 lift < CLABSI 0.35 lift (CDC severity proxy)."""
    admission = datetime(2026, 1, 8, 0)
    obs_dt = datetime(2026, 1, 12, 4)
    state_for_day = _state(0.4)
    state_history = [state_for_day for _ in range(8)]

    baseline = derive_lab_values(state_for_day, sex="M", age=60, hour=4)

    cauti_obs = _obs("CRP", obs_dt, round(baseline["CRP"], 1))
    cauti_rec = SimpleNamespace(
        patient=_patient(),
        extensions={"hai": [_hai_event(hai_type="CAUTI")]},
        lab_results=[cauti_obs],
    )
    apply_hai_lab_lift(cauti_rec, _encounter(), state_history, admission)

    clabsi_obs = _obs("CRP", obs_dt, round(baseline["CRP"], 1))
    clabsi_rec = SimpleNamespace(
        patient=_patient(),
        extensions={"hai": [_hai_event(hai_type="CLABSI")]},
        lab_results=[clabsi_obs],
    )
    apply_hai_lab_lift(clabsi_rec, _encounter(), state_history, admission)

    assert cauti_obs.value < clabsi_obs.value
    assert cauti_obs.value > round(baseline["CRP"], 1)


@pytest.mark.integration
def test_value_preserves_noise_via_delta_addition():
    """If the original obs.value includes synthetic 'noise', the delta is
    additive — final value = original + clean_delta, preserving the noise."""
    admission = datetime(2026, 1, 8, 0)
    obs_dt = datetime(2026, 1, 12, 4)
    state_for_day = _state(0.4)
    state_history = [state_for_day for _ in range(8)]

    baseline = derive_lab_values(state_for_day, sex="M", age=60, hour=4)
    noise = 1234.5  # arbitrary "noise" the daily loop might have produced
    seeded = round(baseline["WBC"] + noise, 1)

    lifted = derive_lab_values(
        state_for_day, sex="M", age=60, hour=4, hai_inflammation_lift=0.35,
    )
    expected_after = round(seeded + (lifted["WBC"] - baseline["WBC"]), 1)

    obs = _obs("WBC", obs_dt, seeded)
    record = SimpleNamespace(
        patient=_patient(),
        extensions={"hai": [_hai_event()]},
        lab_results=[obs],
    )
    apply_hai_lab_lift(record, _encounter(), state_history, admission)
    assert obs.value == pytest.approx(expected_after, abs=0.2)
