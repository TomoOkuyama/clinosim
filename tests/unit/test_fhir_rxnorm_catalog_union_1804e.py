"""Phase 2.e of META #1804 — closes #1765: FHIR emit path resolves
RxNorm through the Phase 1b drug-identity catalog.

Pins the behaviour that ``load_code_mapping("drug", country)`` now
returns a UNION of the legacy ``code_mapping_drug.yaml`` entries and
the catalog's EN-name → RxNorm pointers. Legacy wins on key collision
(backwards compat); catalog fills the gap for drug names the legacy
yaml never registered. Pre-Phase 2.e the US cohort emit path missed
RxNorm coding on ~26 % of MedicationRequests because 78 of the
catalog's unique EN names had no matching legacy entry.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from clinosim.codes.drugs import all_drug_ids, resolve_drug
from clinosim.locale.loader import load_code_mapping

pytestmark = pytest.mark.unit

_US_YAML = Path(__file__).resolve().parents[1].parent / "clinosim" / "locale" / "us" / "code_mapping_drug.yaml"


def _legacy_us() -> dict[str, str]:
    with _US_YAML.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


# ----------------------------------------------------------------------------
# Union semantics
# ----------------------------------------------------------------------------


def test_us_mapping_includes_all_legacy_entries() -> None:
    """The union must preserve every entry the legacy yaml carried
    verbatim — nothing lost on migration."""
    legacy = _legacy_us()
    merged = load_code_mapping("drug", "us")
    missing: list[str] = []
    for name, rxcui in legacy.items():
        if merged.get(name) != rxcui:
            missing.append(f"{name}: legacy={rxcui} merged={merged.get(name)!r}")
    assert not missing, "legacy entries altered by union: " + "; ".join(missing)


def test_us_mapping_adds_catalog_only_entries() -> None:
    """Every catalog entry whose EN name is not in the legacy yaml now
    resolves via the merged mapping — this closes the #1765 gap."""
    legacy = _legacy_us()
    merged = load_code_mapping("drug", "us")
    added = 0
    for drug_id in all_drug_ids():
        rec = resolve_drug(drug_id)
        en = (rec.names.get("en") or "").strip()
        rx = (rec.codes.get("rxnorm") or "").strip()
        if en and rx and en not in legacy:
            assert merged.get(en) == rx, f"catalog-only entry {drug_id!r} ({en!r}) not surfaced in merged mapping"
            added += 1
    assert added > 0, "no catalog-only entries detected — union is a no-op (regression)"


def test_us_mapping_legacy_wins_on_key_collision() -> None:
    """When a drug name exists in BOTH the legacy yaml and the catalog
    with DIFFERENT codes, the legacy entry stays. This preserves the
    pre-Phase-2.e behaviour exactly for every name the legacy yaml
    ever claimed, so byte-level FHIR emit is unchanged for those
    drugs."""
    legacy = _legacy_us()
    merged = load_code_mapping("drug", "us")
    # Find overlap keys where catalog and legacy carry the same name.
    overlap_tested = 0
    for drug_id in all_drug_ids():
        rec = resolve_drug(drug_id)
        en = (rec.names.get("en") or "").strip()
        rx_catalog = (rec.codes.get("rxnorm") or "").strip()
        if en and en in legacy:
            assert merged[en] == legacy[en], (
                f"legacy entry {en!r} shadowed by catalog ({merged[en]!r} vs legacy {legacy[en]!r})"
            )
            overlap_tested += 1
            # If catalog has a different RxCUI than legacy, that would
            # be a data-quality finding, not a union defect — this test
            # is strictly about collision semantics.
            _ = rx_catalog
    assert overlap_tested > 0, "no overlap entries — union coverage check vacuous"


# ----------------------------------------------------------------------------
# Known pre-fix gap entries now resolve
# ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "en,expected_rxcui",
    [
        ("Methyldopa", "6876"),  # Phase 2.c addition
        ("Prednisone", "8640"),  # Phase 2.d pilot addition
        ("Carboplatin", "40048"),  # Phase 2.c chemo addition
        ("Pemetrexed", "68446"),
        ("Paclitaxel", "56946"),
        ("Albuterol", "435"),  # pre-existing catalog, missing from legacy
        ("Anastrozole", "84857"),
        ("Alprazolam", "596"),
        ("Fluorouracil", "4492"),
        ("Folic acid", "4511"),
    ],
)
def test_pre_fix_gap_drug_now_resolves_us_rxnorm(en: str, expected_rxcui: str) -> None:
    """Drugs that pre-Phase-2.e dropped off the US RxNorm coverage
    report (because the legacy yaml had no entry) now resolve through
    the catalog union."""
    assert load_code_mapping("drug", "us").get(en) == expected_rxcui


# ----------------------------------------------------------------------------
# Non-drug domains unchanged
# ----------------------------------------------------------------------------


def test_non_drug_domains_unchanged() -> None:
    """The union is drug-domain-only; lab / diagnosis / procedure
    mappings continue to come from the legacy yaml alone."""
    lab = load_code_mapping("lab", "us")
    assert lab, "US lab code mapping must not be empty"
    # No RxCUI-looking entries in a lab mapping.
    assert "Methyldopa" not in lab
