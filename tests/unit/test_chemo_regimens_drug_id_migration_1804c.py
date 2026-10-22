"""Phase 2.c (chemo) of META #1804: chemo_regimens.yaml drug_id migration.

Pins:
- Every migrated cycle_orders entry in
  ``clinosim/locale/shared/chemo_regimens.yaml`` carries a ``drug_id``
  that resolves against the Phase 1b
  ``clinosim/codes/data/drugs.yaml`` catalog.
- The three new catalog entries (Carboplatin, Pemetrexed, Paclitaxel)
  resolve with EN+JA displays from RxNav-verified ingredient RxCUIs.
- Two entries intentionally stay on the legacy ``drug`` / ``drug_ja``
  shape and are carried by the dual-path resolver:
    * Nab-paclitaxel — SBD-level formulation of Paclitaxel; the Phase 1b
      catalog only models IN-level pointers.
    * BCG intravesical — Mycobacterium bovis BCG antigen (MTHSPL RxCUI
      42579) is not an RXNORM TTY=IN concept.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from clinosim.codes.drugs import resolve_drug
from clinosim.locale.loader import load_chemo_regimens

pytestmark = pytest.mark.unit

_YAML = Path(__file__).resolve().parents[1].parent / "clinosim" / "locale" / "shared" / "chemo_regimens.yaml"


def test_new_catalog_entries_present() -> None:
    """Carboplatin / Pemetrexed / Paclitaxel added to drugs.yaml."""
    for drug_id, en, ja, rxcui in [
        ("carboplatin", "Carboplatin", "カルボプラチン", "40048"),
        ("pemetrexed", "Pemetrexed", "ペメトレキセド", "68446"),
        ("paclitaxel", "Paclitaxel", "パクリタキセル", "56946"),
    ]:
        rec = resolve_drug(drug_id)
        assert rec.names.get("en") == en, f"{drug_id} EN mismatch"
        assert rec.names.get("ja") == ja, f"{drug_id} JA mismatch"
        assert rec.codes.get("rxnorm") == rxcui, f"{drug_id} RxCUI mismatch"


def test_migrated_entries_have_drug_id() -> None:
    """Every migrated cycle_orders entry has drug_id; the two
    documented legacy exceptions (Nab-paclitaxel, BCG) still use the
    legacy drug/drug_ja fields."""
    with _YAML.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    regimens = data.get("regimens") or {}
    legacy_exceptions = {"Nab-paclitaxel", "BCG"}
    offenders: list[str] = []
    for name, spec in regimens.items():
        for idx, order in enumerate((spec or {}).get("cycle_orders", []) or []):
            if "drug_id" in order:
                continue
            if order.get("drug") in legacy_exceptions:
                continue
            offenders.append(f"{name}[{idx}] has no drug_id and is not a documented legacy exception")
    assert not offenders, "; ".join(offenders)


def test_every_drug_id_resolves_in_catalog() -> None:
    """Every drug_id reference in chemo_regimens.yaml must resolve."""
    regimens = load_chemo_regimens().get("regimens") or {}
    offenders: list[str] = []
    for name, spec in regimens.items():
        for idx, order in enumerate((spec or {}).get("cycle_orders", []) or []):
            drug_id = order.get("drug_id")
            if not drug_id:
                continue
            try:
                rec = resolve_drug(drug_id)
            except Exception as e:
                offenders.append(f"{name}[{idx}] drug_id={drug_id}: {e}")
                continue
            assert rec.names.get("en"), f"{name}[{idx}] drug_id={drug_id} has no EN name"
            assert rec.names.get("ja"), f"{name}[{idx}] drug_id={drug_id} has no JA name"
    assert not offenders, "; ".join(offenders)


def test_folfox_regimen_resolves_three_drugs_via_catalog() -> None:
    """FOLFOX cycle_orders now carry drug_id; resolving via the
    catalog returns the full Oxaliplatin / Leucovorin / Fluorouracil
    trio with EN+JA displays — no yaml-side strings consulted."""
    regimens = load_chemo_regimens().get("regimens") or {}
    folfox = regimens.get("FOLFOX") or {}
    orders = folfox.get("cycle_orders") or []
    assert len(orders) == 3
    expected = [("oxaliplatin", "Oxaliplatin"), ("leucovorin", "Leucovorin"), ("fluorouracil", "Fluorouracil")]
    for order, (drug_id, en) in zip(orders, expected, strict=True):
        assert order.get("drug_id") == drug_id
        rec = resolve_drug(order["drug_id"])
        assert rec.names.get("en") == en


def test_lhrh_q28d_leuprorelin_resolves_to_leuprolide_catalog() -> None:
    """The pre-migration yaml used 'Leuprorelin' (JP INN); the catalog
    canonicalises on 'leuprolide' (USAN) with 'リュープロレリン' JA
    alias. Phase 2.a already did this collapse for chronic_medications;
    this test pins the same behaviour for chemo cycles."""
    regimens = load_chemo_regimens().get("regimens") or {}
    orders = (regimens.get("LHRH_q28d") or {}).get("cycle_orders") or []
    assert len(orders) == 1
    assert orders[0].get("drug_id") == "leuprolide"
    rec = resolve_drug("leuprolide")
    assert rec.names.get("ja") == "リュープロレリン"
