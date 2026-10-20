"""Phase 4c Review Focus #2 — BCLC non-numeric state labels round-trip.

Markov loader + step() + initial() must handle string keys with embedded
spaces (BCLC labels like "BCLC 0" / "BCLC A") the same as any state name.
"""

from __future__ import annotations

import numpy as np

from clinosim.modules.longitudinal.loader import load_attribute_specs
from clinosim.modules.longitudinal.patterns.markov import initial, step


def test_bclc_initial_draw_returns_known_state():
    load_attribute_specs.cache_clear()
    spec = load_attribute_specs()["liver_cancer_stage_c22"].body
    for seed in (0, 1, 7, 42, 123):
        s = initial(np.random.default_rng(seed), spec)
        assert s in {"BCLC 0", "BCLC A", "BCLC B", "BCLC C", "BCLC D"}


def test_bclc_step_from_terminal_stays_terminal():
    load_attribute_specs.cache_clear()
    spec = load_attribute_specs()["liver_cancer_stage_c22"].body
    for _ in range(10):
        assert step("BCLC D", np.random.default_rng(0), spec) == "BCLC D"


def test_bclc_step_from_early_may_progress():
    """Over many trials from BCLC 0 the step must sometimes return BCLC A."""
    load_attribute_specs.cache_clear()
    spec = load_attribute_specs()["liver_cancer_stage_c22"].body
    progressed = sum(
        1 for seed in range(100) if step("BCLC 0", np.random.default_rng(seed), spec) == "BCLC A"
    )
    assert progressed > 0, "BCLC 0 never progressed to BCLC A across 100 seeds — Markov row misread"
