"""Drug-safety Japanese display comes from the drug catalog.

Phase 2.f of META #1804 added the catalog path next to the legacy
``drug_ja`` field of the drug-safety class table; Issue #2271 removed the field
and enrolled the drug-safety-only drugs in the catalog, so
``japanese_display`` reads the catalog alone.
"""

from __future__ import annotations

import pytest

from clinosim.codes.drugs import resolve_drug
from clinosim.modules.drug_safety.classifier import (
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


# ----------------------------------------------------------------------------
# Drugs used only by drug-safety rules (enrolled by Issue #2271)
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
def test_japanese_display_covers_drug_safety_only_drugs(drug_name: str, expected_ja: str) -> None:
    """Drugs that only interaction rules reference resolve JA through the
    catalog too."""
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
