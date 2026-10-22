"""Phase 2.c of META #1804: pregnancy_substitutions.yaml drug_id migration.

Pins:
- Every entry in ``clinosim/locale/shared/pregnancy_substitutions.yaml``
  carries ``substitute_drug_id`` resolving against the Phase 1b
  ``clinosim/codes/data/drugs.yaml`` catalog.
- Methyldopa (RxCUI 6876, TTY=IN, NLM RxNav verified) is now a first-
  class entry in drugs.yaml + rxnorm.yaml.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from clinosim.codes.drugs import resolve_drug
from clinosim.locale.loader import load_pregnancy_substitutions

pytestmark = pytest.mark.unit

_YAML = Path(__file__).resolve().parents[1].parent / "clinosim" / "locale" / "shared" / "pregnancy_substitutions.yaml"


def test_methyldopa_in_catalog() -> None:
    """Methyldopa was added to drugs.yaml in Phase 2.c so every
    substitute entry can reference it by drug_id."""
    rec = resolve_drug("methyldopa")
    assert rec.names.get("en") == "Methyldopa"
    assert rec.names.get("ja") == "メチルドパ"
    assert rec.codes.get("rxnorm") == "6876"


def test_every_substitution_entry_has_drug_id() -> None:
    """After Phase 2.c, no entry in pregnancy_substitutions.yaml
    carries the legacy ``substitute`` / ``substitute_ja`` fields —
    every entry references the catalog via ``substitute_drug_id``."""
    with _YAML.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    substitutions = data.get("substitutions") or {}
    assert substitutions, "pregnancy_substitutions.yaml must have 'substitutions' root"
    offenders: list[str] = []
    for orig, entry in substitutions.items():
        if "substitute_drug_id" not in entry:
            offenders.append(f"{orig} missing substitute_drug_id (keys: {sorted(entry)})")
    assert not offenders, "unmigrated entries: " + "; ".join(offenders)


def test_every_substitute_drug_id_resolves_in_catalog() -> None:
    """Every substitute_drug_id must resolve against drugs.yaml."""
    subs = load_pregnancy_substitutions()
    offenders: list[str] = []
    for orig, entry in subs.items():
        drug_id = entry.get("substitute_drug_id", "")
        try:
            rec = resolve_drug(drug_id)
        except Exception as e:
            offenders.append(f"{orig} substitute_drug_id={drug_id!r}: {e}")
            continue
        assert rec.names.get("en"), f"{orig} substitute_drug_id={drug_id} has no EN name"
        assert rec.names.get("ja"), f"{orig} substitute_drug_id={drug_id} has no JA name"
    assert not offenders, "; ".join(offenders)


def test_all_known_pregnancy_substitutes_point_to_methyldopa() -> None:
    """ACOG 2019 first-line for pregnancy chronic HTN is Methyldopa.
    Every current entry (CCB, ACE-I, ARB) swaps to Methyldopa."""
    subs = load_pregnancy_substitutions()
    for orig in ("Amlodipine", "Enalapril", "Lisinopril", "Captopril", "Losartan", "Valsartan", "Candesartan"):
        assert subs[orig]["substitute_drug_id"] == "methyldopa", f"{orig} should swap to methyldopa drug_id"
