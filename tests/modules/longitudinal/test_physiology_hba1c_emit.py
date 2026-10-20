"""Physiology HbA1c emit — AR(1) latent + per-encounter noise overlay.

Validates the Task 8 migration: when `hba1c_latent` is passed,
derive_lab_values emits from the latent + measurement noise; when
`None`, falls back to the protocol-override / non-DM paths.

See Phase 1 plan Task 8 brief.
"""

from __future__ import annotations

import numpy as np
import pytest

from clinosim.modules.longitudinal.loader import load_attribute_specs
from clinosim.modules.physiology import engine as physio
from clinosim.modules.physiology.engine import (
    HBA1C_CLAMP_MAX,
    HBA1C_CLAMP_MIN,
    HBA1C_MEASUREMENT_NOISE_SD,
    derive_lab_values,
    initialize_state,
)
from clinosim.types.patient import PatientPhysiologicalProfile


@pytest.fixture(autouse=True)
def _clear_loader_cache() -> None:
    """Isolate from any sibling test's monkeypatch of _LONGITUDINAL_DIR;
    required for test_physio_hba1c_constants_match_longitudinal_yaml
    to see the real yaml rather than a cached tmp_path spec."""
    load_attribute_specs.cache_clear()
    yield
    load_attribute_specs.cache_clear()


def _mk_state(conditions: list | None = None) -> physio.PhysiologicalState:
    """Baseline healthy state with no protocol override."""
    profile = PatientPhysiologicalProfile()
    return initialize_state(profile=profile, conditions=list(conditions or []))


@pytest.mark.unit
def test_hba1c_emit_reads_from_latent_when_provided() -> None:
    """Pass hba1c_latent=9.1 → emitted value is near 9.1 (within
    3-sigma of the measurement-noise overlay)."""
    state = _mk_state()
    rng = np.random.default_rng(0)
    labs = derive_lab_values(
        state=state,
        sex="M",
        age=55,
        has_diabetes=True,
        rng=rng,
        hba1c_latent=9.1,
    )
    assert "HbA1c" in labs
    assert abs(labs["HbA1c"] - 9.1) < 3 * HBA1C_MEASUREMENT_NOISE_SD + 0.1


@pytest.mark.unit
def test_hba1c_emit_without_latent_falls_through_to_protocol_override() -> None:
    """Protocol-override path: state.glycemic_control is set,
    hba1c_latent is None → emits from hba1c_from_glycemic_control."""
    state = _mk_state()
    state.glycemic_control = 0.3  # protocol forces poor control
    labs = derive_lab_values(
        state=state,
        sex="M",
        age=55,
        has_diabetes=True,
        rng=np.random.default_rng(0),
    )
    expected = physio.hba1c_from_glycemic_control(0.3)
    assert abs(labs["HbA1c"] - expected) < 1e-9


@pytest.mark.unit
def test_hba1c_emit_without_latent_and_no_protocol_falls_through_to_non_dm() -> None:
    """No latent, no protocol override, no has_diabetes → non-DM
    baseline (around 5.4-5.9 depending on age)."""
    state = _mk_state()
    labs = derive_lab_values(
        state=state,
        sex="M",
        age=55,
        has_diabetes=False,
        rng=np.random.default_rng(0),
    )
    assert "HbA1c" in labs
    assert 5.0 <= labs["HbA1c"] <= 6.5


@pytest.mark.unit
def test_hba1c_emit_latent_clamped_to_physiologic_range() -> None:
    """Latent 20.0 is above the physiological ceiling (15.0) — emit
    clamps."""
    state = _mk_state()
    labs = derive_lab_values(
        state=state,
        sex="M",
        age=55,
        has_diabetes=True,
        rng=np.random.default_rng(0),
        hba1c_latent=20.0,
    )
    assert labs["HbA1c"] <= HBA1C_CLAMP_MAX


@pytest.mark.unit
def test_hba1c_emit_latent_clamped_below_floor() -> None:
    state = _mk_state()
    labs = derive_lab_values(
        state=state,
        sex="M",
        age=55,
        has_diabetes=True,
        rng=np.random.default_rng(0),
        hba1c_latent=2.0,
    )
    assert labs["HbA1c"] >= HBA1C_CLAMP_MIN


@pytest.mark.unit
def test_initialize_state_does_not_pull_glycemic_from_chronic() -> None:
    """ChronicCondition.glycemic_control is retired as a Layer-2
    per-encounter write; initialize_state must not pull it up to
    state.glycemic_control any more. (Protocol override at
    inpatient.py:627 is the only writer.)"""
    from clinosim.types.patient import ChronicCondition

    chronic = ChronicCondition(code="E11.9", glycemic_control=0.3)
    state = _mk_state(conditions=[chronic])
    assert state.glycemic_control is None


@pytest.mark.unit
def test_physio_hba1c_constants_match_longitudinal_yaml() -> None:
    """The physiology-engine constants mirror the yaml's
    per_encounter_noise and clamp. Any yaml edit should trip this
    test and remind the maintainer to update the mirror."""
    specs = load_attribute_specs()
    assert specs["hba1c"].body.clamp == [HBA1C_CLAMP_MIN, HBA1C_CLAMP_MAX]
    # The per_encounter_noise.sigma lives on AttributeSpec's
    # auxiliary dict (set via object.__setattr__ in loader._load_one).
    noise = getattr(specs["hba1c"], "_per_encounter_noise", {})
    assert noise.get("sigma") == HBA1C_MEASUREMENT_NOISE_SD
