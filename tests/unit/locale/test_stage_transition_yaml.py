"""Issue #1572 Phase 2.5: `stage_transition.yaml` schema + sanity.

Validates that the yaml loads, carries both CKD + COPD entries,
every stage key appears in the per-stage probability table, and
every rate is a proper Bernoulli value in [0, 1]. The terminal
stage of each disease must have advancement probability 0.
"""

from __future__ import annotations

import pytest

from clinosim.locale.loader import load_stage_transition


def test_yaml_loads_non_empty() -> None:
    data = load_stage_transition()
    assert data, "stage_transition.yaml did not load"
    assert isinstance(data.get("stage_transitions"), dict)


@pytest.mark.parametrize("icd", ["N18", "J44"])
def test_each_disease_has_stages_and_rates(icd: str) -> None:
    """Each disease in the yaml has both a `stages` list and a
    matching `annual_advance_probability` map."""
    cfg = load_stage_transition()["stage_transitions"][icd]
    assert isinstance(cfg["stages"], list) and cfg["stages"]
    probs = cfg["annual_advance_probability"]
    assert set(probs.keys()) == set(cfg["stages"]), f"{icd}: stages/probs key drift"


@pytest.mark.parametrize("icd", ["N18", "J44"])
def test_rates_in_unit_interval(icd: str) -> None:
    cfg = load_stage_transition()["stage_transitions"][icd]
    for stage, p in cfg["annual_advance_probability"].items():
        assert 0.0 <= p <= 1.0, f"{icd} {stage}: {p} out of [0, 1]"


@pytest.mark.parametrize("icd,terminal", [("N18", "CKD G5"), ("J44", "GOLD 4")])
def test_terminal_stage_has_zero_advance(icd: str, terminal: str) -> None:
    """Terminal stages have advance probability 0 — further
    mortality is a `_condition_reactive_mortality` concern."""
    cfg = load_stage_transition()["stage_transitions"][icd]
    assert cfg["annual_advance_probability"][terminal] == 0.0


def test_ckd_order_matches_kdigo() -> None:
    """CKD stages in yaml follow the KDIGO G1 → G2 → G3a → G3b →
    G4 → G5 natural history. The order matters: the body PR
    advances to the next entry in this list."""
    cfg = load_stage_transition()["stage_transitions"]["N18"]
    assert cfg["stages"] == ["CKD G1", "CKD G2", "CKD G3a", "CKD G3b", "CKD G4", "CKD G5"]


def test_copd_order_matches_gold() -> None:
    cfg = load_stage_transition()["stage_transitions"]["J44"]
    assert cfg["stages"] == ["GOLD 1", "GOLD 2", "GOLD 3", "GOLD 4"]


def test_rates_monotone_nondecreasing_through_middle() -> None:
    """Progression accelerates with stage (except terminal). Checks
    that non-terminal rates are weakly non-decreasing from the
    earliest stage inward — simple sanity, not a hard clinical
    invariant."""
    for icd in ("N18", "J44"):
        cfg = load_stage_transition()["stage_transitions"][icd]
        rates = [cfg["annual_advance_probability"][s] for s in cfg["stages"][:-1]]
        for a, b in zip(rates, rates[1:], strict=False):
            assert a <= b, f"{icd}: progression rates not monotone: {rates}"
