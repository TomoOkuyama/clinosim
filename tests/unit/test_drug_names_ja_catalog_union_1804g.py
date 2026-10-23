"""Phase 2.g of META #1804: drug_names_ja.yaml catalog UNION.

Pins the behaviour that ``load_drug_names_ja()`` now returns a UNION
of the legacy ``clinosim/locale/shared/drug_names_ja.yaml`` entries
and the Phase 1b drug-identity catalog's EN-name (lowercased) → JA
display pointers. Legacy wins on key collision (backwards compat);
catalog fills the gap for drug names the legacy yaml never
registered. The 45 catalog-only entries surface through this UNION
so every downstream caller (FHIR emit, imaging_study chief-complaint
localization, discharge-Rx JA display, …) picks up catalog drugs
without each needing its own catalog-aware shim.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from clinosim.codes.drugs import all_drug_ids, resolve_drug
from clinosim.locale.loader import load_drug_names_ja

pytestmark = pytest.mark.unit

_LEGACY_YAML = Path(__file__).resolve().parents[1].parent / "clinosim" / "locale" / "shared" / "drug_names_ja.yaml"


def _legacy_lower() -> dict[str, str]:
    with _LEGACY_YAML.open(encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    return {k.lower(): v for k, v in raw.items()}


# ----------------------------------------------------------------------------
# Union semantics — legacy preserved
# ----------------------------------------------------------------------------


def test_merged_mapping_preserves_every_legacy_entry() -> None:
    legacy = _legacy_lower()
    merged = load_drug_names_ja()
    missing = []
    for k, v in legacy.items():
        if merged.get(k) != v:
            missing.append(f"{k}: legacy={v!r} merged={merged.get(k)!r}")
    assert not missing, "legacy entries altered: " + "; ".join(missing)


def test_merged_mapping_adds_catalog_only_entries() -> None:
    """Every catalog EN name NOT in the legacy yaml now resolves."""
    legacy = _legacy_lower()
    merged = load_drug_names_ja()
    added = 0
    for drug_id in all_drug_ids():
        rec = resolve_drug(drug_id)
        en_lower = (rec.names.get("en") or "").strip().lower()
        ja = (rec.names.get("ja") or "").strip()
        if en_lower and ja and en_lower not in legacy:
            assert merged.get(en_lower) == ja, f"catalog-only drug {drug_id!r} ({en_lower!r} → {ja!r}) not surfaced"
            added += 1
    assert added > 0, "no catalog-only entries surfaced — regression"


def test_legacy_wins_on_key_collision() -> None:
    """When a lowercased EN name exists in BOTH the legacy yaml and
    the catalog with DIFFERENT JA values, the legacy entry stays.

    Known drift surfaced by the audit: Alendronate yaml
    ``アレンドロネート`` vs catalog ``アレンドロン酸``. Legacy wins,
    preserving pre-Phase-2.g display for every caller that already
    read drug_names_ja.yaml.
    """
    merged = load_drug_names_ja()
    assert merged.get("alendronate") == "アレンドロネート"


# ----------------------------------------------------------------------------
# Pre-fix gap drugs now surface JA via the shared lookup API
# ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "en_lower,expected_ja",
    [
        ("methyldopa", "メチルドパ"),  # Phase 2.c addition
        ("prednisone", "プレドニゾン"),  # Phase 2.d pilot addition
        ("carboplatin", "カルボプラチン"),  # Phase 2.c chemo addition
        ("pemetrexed", "ペメトレキセド"),
        ("paclitaxel", "パクリタキセル"),
    ],
)
def test_phase2_catalog_additions_surface_in_drug_names_ja(en_lower: str, expected_ja: str) -> None:
    assert load_drug_names_ja().get(en_lower) == expected_ja
