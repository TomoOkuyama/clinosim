"""Markov pattern `step` unit tests (Phase 2 Task 1)."""

from __future__ import annotations

import numpy as np
import pytest

from clinosim.modules.longitudinal.patterns.markov import MarkovSpec, step


def test_step_advances_on_hit():
    spec = MarkovSpec(
        state_name="ckd_stage",
        icd_base="N18",
        states=["G1", "G2", "G3"],
        initial_distribution={"G1": 1.0},
        transitions={"G1": {"G2": 1.0}, "G2": {"G3": 1.0}, "G3": {}},
    )
    rng = np.random.default_rng(0)
    assert step("G1", rng, spec) == "G2"
    assert step("G2", rng, spec) == "G3"


def test_step_terminal_absorbs():
    spec = MarkovSpec(
        state_name="ckd_stage",
        icd_base="N18",
        states=["G1", "G5"],
        initial_distribution={"G1": 1.0},
        transitions={"G1": {"G5": 0.0}, "G5": {}},
    )
    rng = np.random.default_rng(0)
    assert step("G5", rng, spec) == "G5"
    assert step("G1", rng, spec) == "G1"


def test_step_multiplier_scales_rate():
    spec = MarkovSpec(
        state_name="x",
        icd_base="X",
        states=["A", "B"],
        initial_distribution={"A": 1.0},
        transitions={"A": {"B": 0.1}, "B": {}},
    )
    rng = np.random.default_rng(42)
    hits = sum(1 for _ in range(10000) if step("A", rng, spec, multiplier=5.0) == "B")
    assert 4500 < hits < 5500, f"multiplier=5.0 on p=0.1 expected ~0.5, got {hits / 10000:.3f}"


def test_step_multiplier_clamps_final_probability():
    """Review Focus #4: multiplier that would compound past 1.0 must clamp at the probability level,
    not pre-clamp the multiplier itself."""
    spec = MarkovSpec(
        state_name="x",
        icd_base="X",
        states=["A", "B"],
        initial_distribution={"A": 1.0},
        transitions={"A": {"B": 0.4}, "B": {}},
    )
    rng = np.random.default_rng(0)
    for _ in range(100):
        assert step("A", rng, spec, multiplier=3.0) == "B"


def test_step_unknown_state_raises():
    spec = MarkovSpec(
        state_name="x",
        icd_base="X",
        states=["A", "B"],
        initial_distribution={"A": 1.0},
        transitions={"A": {"B": 0.1}, "B": {}},
    )
    rng = np.random.default_rng(0)
    with pytest.raises(ValueError, match="unknown"):
        step("Z", rng, spec)
