"""Unit tests for `derive_lab_values` hai_inflammation_lift kwarg (Phase 3a).

All expected values are computed from the formulas in the spec §4:
  effective_infl = min(1.0, infl + lift)
  CRP = 0.3 + 400 * effective_infl ** 3
  WBC (<0.8) = 7000 + effective_infl * 12000
  WBC (>=0.8) = max(1500, 7000 + 0.8*12000 - (effective_infl - 0.8) * 30000)

Validates that ONLY CRP + WBC respond to the lift; all other analytes
continue to read state.inflammation_level directly (Phase 3c scope guard).
"""
from __future__ import annotations

import pytest

from clinosim.modules.physiology.engine import derive_lab_values
from clinosim.types.clinical import PhysiologicalState


def _state(infl: float) -> PhysiologicalState:
    return PhysiologicalState(
        inflammation_level=infl,
        renal_function=1.0,
        cardiac_function=1.0,
        hepatic_function=1.0,
        anemia_level=0.0,
        coagulation_status=0.0,
        volume_status=0.0,
        perfusion_status=1.0,
        ph_status=0.0,
        respiratory_fraction=0.0,
        anion_gap_status=0.0,
        glucose_status=0.0,
        sodium_status=0.0,
        glycemic_control=None,
    )


@pytest.mark.unit
def test_baseline_no_lift_unchanged():
    labs = derive_lab_values(_state(0.4), sex="M", age=60, hour=4)
    # baseline CRP = 0.3 + 400 * 0.4**3 = 25.9
    assert labs["CRP"] == pytest.approx(25.9, abs=0.1)
    # baseline WBC = 7000 + 0.4 * 12000 = 11,800
    assert labs["WBC"] == pytest.approx(11800.0, abs=1.0)


@pytest.mark.unit
def test_baseline_with_clabsi_full_lift():
    labs = derive_lab_values(
        _state(0.4), sex="M", age=60, hour=4, hai_inflammation_lift=0.35
    )
    # effective_infl = 0.75 -> CRP = 0.3 + 400 * 0.75**3 = 169.0
    assert labs["CRP"] == pytest.approx(169.0, abs=0.5)
    # WBC = 7000 + 0.75 * 12000 = 16,000
    assert labs["WBC"] == pytest.approx(16000.0, abs=1.0)


@pytest.mark.unit
def test_baseline_with_cauti_full_lift():
    labs = derive_lab_values(
        _state(0.4), sex="M", age=60, hour=4, hai_inflammation_lift=0.20
    )
    # effective_infl = 0.60 -> CRP = 0.3 + 400 * 0.6**3 = 86.7
    assert labs["CRP"] == pytest.approx(86.7, abs=0.5)
    # WBC = 7000 + 0.6 * 12000 = 14,200
    assert labs["WBC"] == pytest.approx(14200.0, abs=1.0)


@pytest.mark.unit
def test_baseline_with_mid_ramp_clabsi():
    labs = derive_lab_values(
        _state(0.4), sex="M", age=60, hour=4, hai_inflammation_lift=0.175
    )
    # effective_infl = 0.575 -> CRP = 0.3 + 400 * 0.575**3 = 76.3
    assert labs["CRP"] == pytest.approx(76.3, abs=0.5)
    # WBC = 7000 + 0.575 * 12000 = 13,900
    assert labs["WBC"] == pytest.approx(13900.0, abs=1.0)


@pytest.mark.unit
def test_clamp_at_high_infl_plus_max_lift():
    labs = derive_lab_values(
        _state(0.8), sex="M", age=60, hour=4, hai_inflammation_lift=0.35
    )
    # effective_infl clamped to 1.0 -> CRP = 0.3 + 400 * 1.0**3 = 400.3
    assert labs["CRP"] == pytest.approx(400.3, abs=0.5)
    # WBC (>=0.8 leg): 7000 + 9600 - (1.0 - 0.8) * 30000 = 16600 - 6000 = 10,600
    assert labs["WBC"] == pytest.approx(10600.0, abs=1.0)


@pytest.mark.unit
def test_high_infl_no_lift_for_comparison():
    labs = derive_lab_values(
        _state(0.95), sex="M", age=60, hour=4, hai_inflammation_lift=0.0
    )
    # CRP = 0.3 + 400 * 0.95**3 = 343.2
    assert labs["CRP"] == pytest.approx(343.2, abs=0.5)
    # WBC = max(1500, 16600 - 0.15 * 30000) = 12,100
    assert labs["WBC"] == pytest.approx(12100.0, abs=1.0)


@pytest.mark.unit
def test_high_infl_with_lift_descending_leg():
    """immune-exhaustion curve: high infl + lift LOWERS WBC vs same infl alone."""
    labs = derive_lab_values(
        _state(0.95), sex="M", age=60, hour=4, hai_inflammation_lift=0.35
    )
    # effective_infl clamped 1.0 -> CRP 400.3, WBC 10,600
    assert labs["CRP"] == pytest.approx(400.3, abs=0.5)
    assert labs["WBC"] == pytest.approx(10600.0, abs=1.0)


@pytest.mark.unit
def test_zero_infl_with_clabsi_lift():
    labs = derive_lab_values(
        _state(0.0), sex="M", age=60, hour=4, hai_inflammation_lift=0.35
    )
    # effective_infl = 0.35 -> CRP = 0.3 + 400 * 0.35**3 = 17.4
    assert labs["CRP"] == pytest.approx(17.4, abs=0.5)
    # WBC = 7000 + 0.35 * 12000 = 11,200
    assert labs["WBC"] == pytest.approx(11200.0, abs=1.0)


@pytest.mark.unit
def test_other_analytes_unaffected_by_lift():
    """Phase 3a scope guard: only WBC + CRP respond. All others use state.inflammation_level."""
    labs_no_lift = derive_lab_values(
        _state(0.4), sex="M", age=60, hour=4, hai_inflammation_lift=0.0
    )
    labs_lifted = derive_lab_values(
        _state(0.4), sex="M", age=60, hour=4, hai_inflammation_lift=0.35
    )
    for key in labs_no_lift:
        if key in ("CRP", "WBC"):
            continue
        assert labs_no_lift[key] == pytest.approx(
            labs_lifted[key], rel=1e-9
        ), (
            f"{key} unexpectedly changed with hai lift "
            f"({labs_no_lift[key]} -> {labs_lifted[key]}); "
            "Phase 3a scope is WBC+CRP only"
        )


@pytest.mark.unit
def test_pct_and_albumin_remain_on_state_infl():
    """PCT and Albumin currently read state.inflammation_level directly.
    Phase 3a does NOT rewire them — they stay on baseline infl per spec §4.
    """
    labs_no_lift = derive_lab_values(
        _state(0.4), sex="M", age=60, hour=4, hai_inflammation_lift=0.0
    )
    labs_lifted = derive_lab_values(
        _state(0.4), sex="M", age=60, hour=4, hai_inflammation_lift=0.35
    )
    assert labs_no_lift["PCT"] == pytest.approx(labs_lifted["PCT"], rel=1e-9)
    assert labs_no_lift["Albumin"] == pytest.approx(
        labs_lifted["Albumin"], rel=1e-9
    )
