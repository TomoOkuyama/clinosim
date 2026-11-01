"""Decision logic identifies drugs by drug_id, not name substrings (Issue #2377)."""

from __future__ import annotations

import pytest

from clinosim.codes.drugs import drug_key, same_drug
from clinosim.simulator.discharge_rx import _dedup_key, renal_hold_drugs
from clinosim.simulator.medication_pipeline import mar_vital_hold_reason, renal_medication_rules

pytestmark = pytest.mark.unit


def test_same_drug_by_id_name_alias_and_japanese() -> None:
    assert same_drug("Metformin 500mg", "metformin")
    assert same_drug("メトホルミン", "Metformin")
    assert same_drug("Coumadin", "ワルファリン")
    assert not same_drug("Metformin", "Glimepiride")


def test_uncatalogued_names_compare_whole_names_only() -> None:
    assert drug_key("  Some  Unknown Drug ") == "some unknown drug"
    assert not same_drug("Unknown", "Unknown Drug")


def test_renal_rules_are_keyed_by_drug_id() -> None:
    rules = renal_medication_rules()
    assert rules["metformin"] == "hold"
    assert "ibuprofen" in renal_hold_drugs()
    assert rules.get(drug_key("イブプロフェン")) == "hold"


def test_dedup_key_merges_english_and_japanese_names() -> None:
    assert _dedup_key("Amlodipine") == _dedup_key("アムロジピン") == "amlodipine"


def test_vital_hold_matches_the_drug_not_a_substring() -> None:
    class _V:
        systolic_bp = 85
        heart_rate = 70

    assert mar_vital_hold_reason("Amlodipine 5mg", _V()) == "SBP < 90"
    assert mar_vital_hold_reason("アムロジピン", _V()) == "SBP < 90"


def test_uncatalogued_combination_is_not_one_of_its_ingredients() -> None:
    assert drug_key("Oxycodone/Acetaminophen") != drug_key("Acetaminophen")
    assert not same_drug("Amlodipine/Benazepril", "Amlodipine")
    # Catalogued combinations and "mg/kg" doses still resolve.
    assert drug_key("Acetaminophen / Codeine") == "acetaminophen_codeine"
    assert drug_key("Enoxaparin 1mg/kg SC q12h") == "enoxaparin"


def test_prefixed_catalogued_combination_still_resolves() -> None:
    assert drug_key("DISCONTINUE: Piperacillin/Tazobactam") == "piperacillin_tazobactam"
