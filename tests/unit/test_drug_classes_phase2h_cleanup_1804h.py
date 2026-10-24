"""Phase 2.h of META #1804: drug_classes.yaml redundant drug_ja cleanup.

Phase 2.f (#1821) added the dual-path resolver so ``japanese_display``
reads from the Phase 1b catalog first, legacy ``drug_ja`` field second.
Phase 2.h is the actual yaml cleanup: for the 34 drugs that resolve
through the catalog, their inline ``drug_ja`` field is now redundant
and retired. The 18 drugs not yet in the catalog keep their inline
``drug_ja`` as the only JA source (dual-path fallback branch).

Downstream behaviour unchanged — the dual-path resolver already
prefers the catalog, so every covered drug's ``japanese_display``
result stays byte-identical.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from clinosim.codes.drugs import all_drug_ids, resolve_drug
from clinosim.modules.drug_safety.classifier import japanese_display

pytestmark = pytest.mark.unit

_YAML = (
    Path(__file__).resolve().parents[1].parent
    / "clinosim"
    / "modules"
    / "drug_safety"
    / "reference_data"
    / "drug_classes.yaml"
)


def _load_mappings() -> dict[str, dict]:
    with _YAML.open(encoding="utf-8") as fh:
        return (yaml.safe_load(fh) or {}).get("mappings", {}) or {}


def _catalog_en_lower() -> set[str]:
    out: set[str] = set()
    for did in all_drug_ids():
        rec = resolve_drug(did)
        en = (rec.names.get("en") or "").strip().lower()
        if en:
            out.add(en)
    return out


# ----------------------------------------------------------------------------
# 34 catalog-covered drugs no longer carry drug_ja
# ----------------------------------------------------------------------------


def test_catalog_covered_drugs_have_drug_ja_removed() -> None:
    """Every drug_classes.yaml entry whose name matches a catalog
    entry (case-insensitive) must NOT carry an inline ``drug_ja`` any
    more — the catalog's names.ja is now the single source of truth."""
    mappings = _load_mappings()
    cat_en = _catalog_en_lower()
    offenders = []
    for name, entry in mappings.items():
        if name.lower() in cat_en and entry.get("drug_ja"):
            offenders.append(f"{name}: still carries drug_ja={entry['drug_ja']!r}")
    assert not offenders, "catalog-covered drugs with redundant drug_ja:\n" + "\n".join(offenders)


def test_japanese_display_still_resolves_for_covered_drugs() -> None:
    """After the yaml cleanup, every catalog-covered drug still
    returns a JA display via the Phase 2.f dual-path resolver — the
    catalog branch wins and the retired ``drug_ja`` field is not
    needed."""
    mappings = _load_mappings()
    cat_en = _catalog_en_lower()
    offenders = []
    for name in mappings:
        if name.lower() in cat_en:
            ja = japanese_display(name)
            if not ja:
                offenders.append(f"{name}: japanese_display returned {ja!r}")
    assert not offenders, "; ".join(offenders)


# ----------------------------------------------------------------------------
# 18 non-catalog drugs keep their inline drug_ja
# ----------------------------------------------------------------------------


def test_non_catalog_drugs_still_carry_drug_ja() -> None:
    """Drugs not yet enrolled in the Phase 1b catalog (Dabigatran,
    Edoxaban, Prasugrel, several NSAIDs, ...) KEEP their inline
    ``drug_ja`` — the dual-path legacy branch is the only JA source
    for them, so retiring the field would break ``japanese_display``."""
    mappings = _load_mappings()
    cat_en = _catalog_en_lower()
    missing = []
    for name, entry in mappings.items():
        if name.lower() not in cat_en:
            if not entry.get("drug_ja"):
                missing.append(name)
    assert not missing, "non-catalog drugs missing drug_ja (would break japanese_display): " + ", ".join(missing)


def test_japanese_display_still_resolves_for_non_catalog_drugs() -> None:
    """A non-catalog drug (e.g. Dabigatran) still returns a JA
    display — the dual-path legacy branch supplies it from the
    retained ``drug_ja`` field."""
    assert japanese_display("Dabigatran") == "ダビガトラン"
    assert japanese_display("Edoxaban") == "エドキサバン"
    assert japanese_display("Metoprolol") == "メトプロロール"


# ----------------------------------------------------------------------------
# Known regression — Ketorolac drift resolution
# ----------------------------------------------------------------------------


def test_ketorolac_catalog_display_wins_post_cleanup() -> None:
    """Phase 2.f noted a drift: yaml said ``"ケトロラック"`` (promoted
    sokuon) vs catalog ``"ケトロラク"``. After the yaml drug_ja field
    is retired, the catalog display becomes authoritative — the drift
    is resolved in favour of the standard katakana rendering."""
    assert japanese_display("Ketorolac") == "ケトロラク"
