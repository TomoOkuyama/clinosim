"""Unit tests for check_pair and check_candidate_against_active."""

from __future__ import annotations

import numpy as np

from clinosim.modules.drug_safety.engine import (
    check_candidate_against_active,
    check_pair,
)


def test_warfarin_plus_aspirin_contraindicated() -> None:
    v = check_pair("Warfarin", "Aspirin")
    assert v.severity == "contraindicated"
    assert v.rule_id == "vka-plus-antiplatelet"
    assert v.rationale_en is not None
    assert v.rationale_ja is not None


def test_order_independence() -> None:
    a = check_pair("Warfarin", "Ibuprofen")
    b = check_pair("Ibuprofen", "Warfarin")
    assert a.severity == b.severity == "contraindicated"
    assert a.rule_id == b.rule_id


def test_unrelated_pair_is_allowed() -> None:
    v = check_pair("Acetaminophen", "Amlodipine")
    assert v.severity == "allowed"


def test_unknown_drug_pair_is_allowed() -> None:
    v = check_pair("Metformin", "Acetaminophen")  # Metformin not yet in yaml
    assert v.severity == "allowed"


def test_metoprolol_verapamil_is_major_not_contraindicated() -> None:
    v = check_pair("Metoprolol", "Verapamil")
    assert v.severity == "major"
    assert v.rule_id == "bb-plus-non-dhp-ccb"


def test_amlodipine_plus_metoprolol_is_allowed() -> None:
    """DHP CCB + BB is safe — only non-DHP CCB is the interaction risk."""
    v = check_pair("Amlodipine", "Metoprolol")
    assert v.severity == "allowed"


def test_check_candidate_against_active_multiple_hits() -> None:
    verdicts = check_candidate_against_active("Aspirin", ["Warfarin", "Amlodipine"])
    assert len(verdicts) == 1
    assert verdicts[0].matched_active_drug == "Warfarin"
    assert verdicts[0].severity == "contraindicated"


def test_check_candidate_against_active_empty_when_safe() -> None:
    assert check_candidate_against_active("Acetaminophen", ["Warfarin"]) == []


def test_check_candidate_alias_active_drug() -> None:
    """Active meds passed as JP/alias must still trigger the gate."""
    verdicts = check_candidate_against_active("Aspirin", ["ワルファリン"])
    assert len(verdicts) == 1
    assert verdicts[0].matched_active_drug == "Warfarin"


def test_check_pair_does_not_consume_rng() -> None:
    """Verdict is a pure lookup — must not touch numpy Generator state."""
    rng = np.random.default_rng(seed=42)
    state_before = rng.bit_generator.state
    check_pair("Warfarin", "Aspirin")
    check_candidate_against_active("Ibuprofen", ["Warfarin"])
    assert rng.bit_generator.state == state_before


def test_ssri_plus_maoi_contraindicated() -> None:
    v = check_pair("Sertraline", "Selegiline")
    assert v.severity == "contraindicated"
    assert v.rule_id == "ssri-plus-maoi"


def test_allopurinol_plus_azathioprine_contraindicated() -> None:
    v = check_pair("Allopurinol", "Azathioprine")
    assert v.severity == "contraindicated"


def test_atorvastatin_plus_clarithromycin_major() -> None:
    v = check_pair("Atorvastatin", "Clarithromycin")
    assert v.severity == "major"
