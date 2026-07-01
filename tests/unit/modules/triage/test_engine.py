"""Unit tests for triage engine(Tier 1 #3 α-min-2 PR1)."""

from __future__ import annotations

import numpy as np

from clinosim.modules.triage.engine import (
    SUPPORTED_ARRIVAL_MODES,
    SUPPORTED_LEVEL_SYSTEMS,
    load_triage_protocols,
    pick_arrival_mode,
    pick_triage_level,
)


def test_load_triage_protocols_returns_both_systems():
    p = load_triage_protocols()
    assert "JTAS" in p["triage_systems"]
    assert "ESI" in p["triage_systems"]


def test_supported_sets():
    assert SUPPORTED_LEVEL_SYSTEMS == frozenset({"JTAS", "ESI"})
    assert "walk-in" in SUPPORTED_ARRIVAL_MODES


def test_pick_triage_level_mild_jtas():
    """Mild severity → mostly level 4-5 (JTAS)."""
    rng = np.random.default_rng(42)
    counts = {"1": 0, "2": 0, "3": 0, "4": 0, "5": 0}
    for _ in range(1000):
        level = pick_triage_level("mild", "JTAS", rng)
        counts[level] += 1
    # mild は 3-5 に集中(distribution 準拠)
    assert counts["1"] == 0
    assert counts["2"] == 0
    assert counts["4"] + counts["5"] >= 700  # 70%+


def test_pick_triage_level_severe_esi():
    """Severe severity → mostly level 1-2 (ESI)."""
    rng = np.random.default_rng(42)
    counts = {"1": 0, "2": 0, "3": 0, "4": 0, "5": 0}
    for _ in range(1000):
        level = pick_triage_level("severe", "ESI", rng)
        counts[level] += 1
    # severe は 1-2 に集中
    assert counts["1"] + counts["2"] >= 700  # 70%+


def test_pick_arrival_mode_returns_valid():
    rng = np.random.default_rng(42)
    for _ in range(100):
        mode = pick_arrival_mode("moderate", rng)
        assert mode in SUPPORTED_ARRIVAL_MODES


def test_pick_triage_level_deterministic():
    rng1 = np.random.default_rng(42)
    rng2 = np.random.default_rng(42)
    assert pick_triage_level("mild", "JTAS", rng1) == pick_triage_level("mild", "JTAS", rng2)
