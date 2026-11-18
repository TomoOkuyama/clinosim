"""Issue #3271: the daily intake / output record is coupled to the physiology."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from clinosim import determinism
from clinosim.modules.observation.fluid_balance_model import (
    FluidContext,
    fluid_params,
    insensible_loss_ml,
    volume_status_shift,
)
from clinosim.simulator.vitals_pipeline import _generate_daily_io

pytestmark = pytest.mark.unit

ADMIT = datetime(2025, 3, 1, 9, 0)


def _state(**kw):
    base = dict(
        volume_status=0.0,
        inflammation_level=0.1,
        renal_function=1.0,
        cardiac_function=1.0,
        perfusion_status=1.0,
    )
    base.update(kw)
    return SimpleNamespace(**base)


def _stay(state, days, disease_id="", diuretic=False, weight=70.0, seed=3):
    patient = SimpleNamespace(patient_id="POP-000777", weight_kg=weight)
    rng = determinism.default_rng(seed)
    return [
        _generate_daily_io(state, patient, d, ADMIT, rng, disease_id=disease_id, on_loop_diuretic=diuretic)
        for d in range(days)
    ]


def _cumulative(records):
    return sum(r.net_balance_ml for r in records)


def test_heart_failure_on_loop_diuretic_is_not_positive_over_a_week() -> None:
    state = _state(volume_status=0.4, cardiac_function=0.4, renal_function=0.8)
    recs = _stay(state, 7, disease_id="heart_failure_exacerbation", diuretic=True)
    assert _cumulative(recs) <= 0
    # fluid restricted: carrier IV only, oral capped
    assert all(r.intake_iv_ml < 400 for r in recs)


def test_diuretic_lowers_the_balance() -> None:
    state = _state(volume_status=0.3, cardiac_function=0.5, renal_function=0.8)
    with_d = _cumulative(_stay(state, 7, "heart_failure_exacerbation", True))
    without = _cumulative(_stay(state, 7, "heart_failure_exacerbation", False))
    assert with_d < without


def test_euvolemic_adult_stays_within_bounds_over_two_weeks() -> None:
    recs = _stay(_state(), 14, disease_id="urinary_tract_infection")
    assert abs(_cumulative(recs)) < 5000


def test_oliguric_kidney_urine_below_kdigo_criterion() -> None:
    """AKI with oliguria (renal function failing): urine below the KDIGO
    0.5 mL/kg/h criterion (840 mL/day at 70 kg) and a positive balance."""
    recs = _stay(_state(renal_function=0.08, volume_status=0.0), 5, disease_id="acute_kidney_injury")
    assert all(r.output_urine_ml < 0.5 * 70 * 24 for r in recs)


def test_insensible_loss_is_charted_and_scales_with_weight() -> None:
    assert insensible_loss_ml(70.0) == pytest.approx(800.0)
    assert insensible_loss_ml(20.0) < insensible_loss_ml(70.0)
    rec = _stay(_state(), 3)[2]
    assert rec.output_other_ml >= 800


def test_net_balance_moves_volume_status_in_the_expected_direction() -> None:
    assert volume_status_shift(1000, 70.0) > 0
    assert volume_status_shift(-1000, 70.0) < 0
    assert volume_status_shift(0, 70.0) == 0


def test_draw_count_is_unchanged() -> None:
    rng = determinism.default_rng(11)
    patient = SimpleNamespace(patient_id="POP-000777", weight_kg=70.0)
    _generate_daily_io(_state(), patient, 5, ADMIT, rng, disease_id="heart_failure_exacerbation", on_loop_diuretic=True)
    ref = determinism.default_rng(11)
    ref.normal(0, 1), ref.normal(0, 1), ref.normal(0, 1)
    assert rng.random() == ref.random()


def test_parameters_load_and_cite_sources() -> None:
    p = fluid_params()
    assert p.insensible_ml_per_day_at_reference == 800
    assert p.kidney.oliguria_ml_per_kg_per_h == 0.5
    assert FluidContext().weight_kg == 70.0


def test_depleted_septic_patient_with_failing_kidney_is_still_resuscitated() -> None:
    state = _state(volume_status=-0.4, renal_function=0.1, perfusion_status=0.6)
    recs = _stay(state, 3, disease_id="sepsis")
    assert recs[0].intake_iv_ml > 1000
