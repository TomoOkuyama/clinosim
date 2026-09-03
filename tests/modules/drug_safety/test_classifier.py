"""Unit tests for drug_safety.classifier."""

from __future__ import annotations

import pytest

from clinosim.modules.drug_safety.classifier import (
    canonical_name,
    japanese_display,
    resolve_classes,
)


@pytest.mark.parametrize(
    "drug_name",
    ["Warfarin", "warfarin", "WARFARIN", "ワルファリン", "coumadin", " warfarin "],
)
def test_warfarin_resolves_to_vka_classes(drug_name: str) -> None:
    classes = resolve_classes(drug_name)
    assert "anticoagulant.vka" in classes
    assert "anticoagulant" in classes


def test_aspirin_dual_class_membership() -> None:
    """Aspirin is both an antiplatelet.cox_inhibitor AND an nsaid.non_selective."""
    classes = resolve_classes("Aspirin")
    assert "antiplatelet.cox_inhibitor" in classes
    assert "antiplatelet" in classes
    assert "nsaid.non_selective" in classes
    assert "nsaid" in classes


def test_unknown_drug_returns_empty_list() -> None:
    assert resolve_classes("Unobtainium-500") == []
    assert canonical_name("Unobtainium-500") is None
    assert japanese_display("Unobtainium-500") is None


def test_canonical_name_normalizes() -> None:
    assert canonical_name("warfarin") == "Warfarin"
    assert canonical_name("ワルファリン") == "Warfarin"
    assert canonical_name("Aspirin") == "Aspirin"


def test_japanese_display() -> None:
    assert japanese_display("Warfarin") == "ワルファリン"
    assert japanese_display("Aspirin") == "アスピリン"


def test_substring_match_with_dose_suffix() -> None:
    """Real MR strings often carry a dose ('Warfarin 3mg PO') — must match."""
    assert canonical_name("Warfarin 3mg PO daily") == "Warfarin"
    assert canonical_name("アムロジピン 5mg") == "Amlodipine"


def test_verapamil_is_non_dhp_ccb() -> None:
    classes = resolve_classes("Verapamil")
    assert "ccb.non_dhp" in classes
    assert "ccb" in classes
    assert "ccb.dhp" not in classes


def test_amlodipine_is_dhp_ccb() -> None:
    classes = resolve_classes("Amlodipine")
    assert "ccb.dhp" in classes
    assert "ccb.non_dhp" not in classes
