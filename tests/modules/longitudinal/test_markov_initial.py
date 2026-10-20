"""Markov pattern `initial` distribution shape test (Phase 2 Task 1)."""

from __future__ import annotations

import numpy as np

from clinosim.modules.longitudinal.patterns.markov import MarkovSpec, initial


def test_initial_matches_distribution():
    spec = MarkovSpec(
        state_name="ckd_stage",
        icd_base="N18",
        states=["G1", "G2", "G3", "G4", "G5"],
        initial_distribution={"G1": 0.20, "G2": 0.45, "G3": 0.20, "G4": 0.10, "G5": 0.05},
        transitions={},
    )
    rng = np.random.default_rng(42)
    draws = [initial(rng, spec) for _ in range(10000)]
    counts = {s: draws.count(s) / 10000 for s in spec.states}
    assert abs(counts["G2"] - 0.45) < 0.02, counts
    assert abs(counts["G5"] - 0.05) < 0.02, counts
