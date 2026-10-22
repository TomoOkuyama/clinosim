"""Phase 2.b of META #1804: drug_substitution.yaml drug_id migration.

Pins:
- Every ``alternatives[]`` entry in
  ``clinosim/locale/shared/drug_substitution.yaml`` carries a
  ``drug_id`` that resolves against the Phase 1b
  ``clinosim/codes/data/drugs.yaml`` catalog.
- The engine's ``_shared_pool_pick`` resolves display via
  ``clinosim.codes.drugs.resolve_drug`` so the returned
  ``AlternativeDrug.drug`` / ``.drug_ja`` match the catalog's EN / JA.
- Legacy ``drug`` / ``drug_ja`` field pairs (not present after this
  migration, but kept supported via dual-path) still work when a
  caller injects a hand-crafted entry.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from clinosim.codes.drugs import resolve_drug
from clinosim.modules.drug_safety.engine import (
    _load_shared_substitutions,
    _resolve_substitution_display,
    _shared_pool_pick,
)

pytestmark = pytest.mark.unit

_YAML = Path(__file__).resolve().parents[1].parent / "clinosim" / "locale" / "shared" / "drug_substitution.yaml"


# ----------------------------------------------------------------------------
# YAML shape invariant — every entry has drug_id (post-migration)
# ----------------------------------------------------------------------------


def test_every_alternative_entry_has_drug_id() -> None:
    """After Phase 2.b, no entry in drug_substitution.yaml carries the
    legacy ``drug`` / ``drug_ja`` fields — every entry references the
    catalog via ``drug_id``."""
    with _YAML.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    indications = data.get("indications") or {}
    assert indications, "drug_substitution.yaml must have 'indications' root"
    offenders: list[str] = []
    for ind_name, block in indications.items():
        for idx, entry in enumerate((block or {}).get("alternatives", []) or []):
            if "drug_id" not in entry:
                offenders.append(f"{ind_name}[{idx}] missing drug_id (keys: {sorted(entry)})")
    assert not offenders, "unmigrated entries: " + "; ".join(offenders)


def test_every_drug_id_resolves_in_catalog() -> None:
    """Every drug_id in drug_substitution.yaml must resolve against
    clinosim/codes/data/drugs.yaml — a typo'd ref is a bug the catalog
    can tell us about."""
    indications = _load_shared_substitutions()
    offenders: list[str] = []
    for ind_name, block in indications.items():
        for idx, entry in enumerate((block or {}).get("alternatives", []) or []):
            drug_id = entry.get("drug_id", "")
            try:
                rec = resolve_drug(drug_id)
            except Exception as e:
                offenders.append(f"{ind_name}[{idx}] drug_id={drug_id!r}: {e}")
                continue
            assert rec.names.get("en"), f"{ind_name}[{idx}] drug_id={drug_id} has no EN name"
            assert rec.names.get("ja"), f"{ind_name}[{idx}] drug_id={drug_id} has no JA name"
    assert not offenders, "; ".join(offenders)


# ----------------------------------------------------------------------------
# Display resolution — catalog is the SoT
# ----------------------------------------------------------------------------


def test_resolve_substitution_display_prefers_drug_id() -> None:
    """A drug_id entry resolves EN+JA from drugs.yaml catalog."""
    en, ja = _resolve_substitution_display({"drug_id": "acetaminophen"})
    assert en == "Acetaminophen"
    assert ja == "アセトアミノフェン"


def test_resolve_substitution_display_falls_back_to_legacy_fields() -> None:
    """Legacy ``drug`` / ``drug_ja`` fields (not present after migration
    but kept supported) still work via the dual-path shim."""
    en, ja = _resolve_substitution_display({"drug": "Legacy-Drug", "drug_ja": "レガシー薬"})
    assert en == "Legacy-Drug"
    assert ja == "レガシー薬"


def test_resolve_substitution_display_empty_entry_returns_empty() -> None:
    """An entry with neither drug_id nor legacy fields returns empty
    strings — caller's safety check will skip it."""
    en, ja = _resolve_substitution_display({"default_dose": "500mg"})
    assert en == ""


# ----------------------------------------------------------------------------
# Integration: _shared_pool_pick returns catalog-sourced display
# ----------------------------------------------------------------------------


def test_shared_pool_pick_returns_catalog_display_for_pain_management() -> None:
    """pain_management picks Acetaminophen; display must come from the
    catalog, not from the yaml file (post-migration)."""
    alt = _shared_pool_pick("pain_management", active_meds=())
    assert alt is not None
    assert alt.drug == "Acetaminophen"
    assert alt.drug_ja == "アセトアミノフェン"
    assert alt.default_dose == "500mg"
    assert alt.default_route == "PO"
    assert alt.default_frequency == "q6h_prn"


def test_shared_pool_pick_returns_catalog_display_for_hypertension() -> None:
    """hypertension picks Amlodipine; display from catalog."""
    alt = _shared_pool_pick("hypertension_or_rate_control", active_meds=())
    assert alt is not None
    assert alt.drug == "Amlodipine"
    assert alt.drug_ja == "アムロジピン"


def test_shared_pool_pick_unknown_indication_returns_none() -> None:
    assert _shared_pool_pick("not_a_real_indication", active_meds=()) is None
