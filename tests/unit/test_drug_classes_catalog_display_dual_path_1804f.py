"""Phase 2.f of META #1804: drug_classes.yaml drug_ja dual-path resolver.

Pins:
- ``japanese_display`` first consults the Phase 1b drug-identity
  catalog (``clinosim/codes/data/drugs.yaml``) when the canonical
  name resolves there.
- Falls back to the legacy ``drug_ja`` field in
  ``drug_classes.yaml`` when the catalog has no matching entry
  (18 drugs not yet enrolled: Dabigatran, Edoxaban, Prasugrel,
  several NSAIDs, …).
- The classifier module exports an internal reverse index
  ``_catalog_en_to_drug_id`` built once and cached.
"""

from __future__ import annotations

import pytest

from clinosim.codes.drugs import resolve_drug
from clinosim.modules.drug_safety.classifier import (
    _catalog_en_to_drug_id,
    canonical_name,
    japanese_display,
)

pytestmark = pytest.mark.unit


# ----------------------------------------------------------------------------
# Catalog-side resolution — drugs enrolled in the Phase 1b catalog
# ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "drug_name,expected_ja",
    [
        ("Warfarin", "ワルファリン"),
        ("Apixaban", "アピキサバン"),
        ("Amlodipine", "アムロジピン"),
        ("Furosemide", "フロセミド"),
        ("Lisinopril", "リシノプリル"),
        ("Carvedilol", "カルベジロール"),
    ],
)
def test_japanese_display_prefers_catalog(drug_name: str, expected_ja: str) -> None:
    """A drug enrolled in the Phase 1b catalog resolves JA via the
    catalog, not the legacy drug_ja field — the catalog is the SoT."""
    assert japanese_display(drug_name) == expected_ja


def test_catalog_reverse_index_populated() -> None:
    """The reverse index must contain at least every catalog drug that
    has an EN name — regression pin against an accidentally empty
    index."""
    idx = _catalog_en_to_drug_id()
    assert "warfarin" in idx
    assert "apixaban" in idx
    assert "amlodipine" in idx
    assert len(idx) >= 100, f"reverse index unexpectedly small ({len(idx)} entries)"


# ----------------------------------------------------------------------------
# Legacy fallback — drugs not enrolled in the catalog
# ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "drug_name,expected_ja",
    [
        ("Dabigatran", "ダビガトラン"),
        ("Edoxaban", "エドキサバン"),
        ("Prasugrel", "プラスグレル"),
        ("Loxoprofen", "ロキソプロフェン"),
        ("Metoprolol", "メトプロロール"),
        ("Verapamil", "ベラパミル"),
        ("Clarithromycin", "クラリスロマイシン"),
        ("Diazepam", "ジアゼパム"),
    ],
)
def test_japanese_display_falls_back_to_legacy_field(drug_name: str, expected_ja: str) -> None:
    """A drug NOT in the catalog resolves JA via the legacy drug_ja
    field in drug_classes.yaml — the dual-path shim keeps these
    functional until catalog enrichment catches up."""
    assert japanese_display(drug_name) == expected_ja


# ----------------------------------------------------------------------------
# Edge cases
# ----------------------------------------------------------------------------


def test_japanese_display_unknown_drug_returns_none() -> None:
    """An entirely-unknown drug returns None (unchanged pre-fix
    behaviour)."""
    assert japanese_display("Not-a-real-drug") is None


def test_japanese_display_alias_resolves_via_catalog() -> None:
    """The classifier's alias / case / substring fallback is upstream
    of the dual path — a known alias ("warf") still resolves JA via
    the catalog once canonical_name finds its target."""
    assert canonical_name("warf") == "Warfarin"
    assert japanese_display("warf") == "ワルファリン"
    # Catalog-sourced JA (not legacy drug_ja field value, which happens
    # to agree here) — pinned by catalog resolution path.
    assert resolve_drug("warfarin").names.get("ja") == "ワルファリン"
