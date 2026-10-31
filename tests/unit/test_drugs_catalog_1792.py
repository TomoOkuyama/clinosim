"""META #1792 Phase 1a — drug identity catalog loader + integrity.

Covers:
    - resolve_drug / get_drug / all_drug_ids API shape
    - display_for locale behavior (JP vs non-JP)
    - fail-loud on missing-row and malformed yaml
    - integrity invariants: every code pointer must resolve against its
      authority code-system yaml (rxnorm / yj / hot7)
    - drug_id uniqueness (yaml-level — a repeated key would silently
      shadow in dict-parse, so the loader catches it earlier)
"""

from __future__ import annotations

from pathlib import Path

import pytest

from clinosim.codes.drugs import (
    DrugIdentity,
    _load_catalog,
    _parse_catalog,
    all_drug_ids,
    get_drug,
    resolve_drug,
)
from clinosim.codes.loader import _load_system

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# API shape
# ---------------------------------------------------------------------------


def test_resolve_drug_returns_identity_for_catalogued_drug():
    rec = resolve_drug("atorvastatin")
    assert isinstance(rec, DrugIdentity)
    assert rec.drug_id == "atorvastatin"
    assert rec.names["en"] == "Atorvastatin"
    assert rec.names["ja"] == "アトルバスタチン"
    assert rec.codes.get("rxnorm") == "83367"
    assert "statin" in rec.classes


def test_resolve_drug_raises_on_unknown_id():
    with pytest.raises(KeyError, match="not in drugs.yaml catalog"):
        resolve_drug("nonexistent_drug_xyz")


def test_get_drug_returns_none_on_unknown_id():
    assert get_drug("nonexistent_drug_xyz") is None


def test_all_drug_ids_is_sorted_tuple():
    ids = all_drug_ids()
    assert isinstance(ids, tuple)
    assert list(ids) == sorted(ids)
    assert len(ids) >= 10  # Phase 1a representative set


# ---------------------------------------------------------------------------
# display_for behavior
# ---------------------------------------------------------------------------


def test_display_for_jp_returns_japanese_name():
    assert resolve_drug("metformin").display_for("JP") == "メトホルミン"


@pytest.mark.parametrize("country", ["US", "us", "", "ZZ", "DE"])
def test_display_for_non_jp_returns_english_name(country: str):
    assert resolve_drug("metformin").display_for(country) == "Metformin"


# ---------------------------------------------------------------------------
# Fail-loud yaml validation
# ---------------------------------------------------------------------------


def test_parse_catalog_rejects_entry_missing_en_name():
    bad = {"drugs": {"broken": {"names": {"ja": "テスト"}}}}
    with pytest.raises(ValueError, match="missing required names.en"):
        _parse_catalog(bad)


def test_parse_catalog_rejects_entry_missing_ja_name():
    bad = {"drugs": {"broken": {"names": {"en": "Broken"}}}}
    with pytest.raises(ValueError, match="missing required names.ja"):
        _parse_catalog(bad)


def test_parse_catalog_rejects_non_mapping_body():
    bad = {"drugs": {"broken": "not a dict"}}
    with pytest.raises(ValueError, match="body must be a mapping"):
        _parse_catalog(bad)


def test_parse_catalog_rejects_non_mapping_codes():
    bad = {"drugs": {"broken": {"names": {"en": "X", "ja": "X"}, "codes": "oops"}}}
    with pytest.raises(ValueError, match="codes must be a mapping"):
        _parse_catalog(bad)


def test_parse_catalog_drops_blank_code_values():
    """An empty-string code pointer MUST NOT make it into the catalog —
    a blank entry would cause the integrity test to falsely report a
    nonexistent authority code."""
    data = {
        "drugs": {
            "d": {
                "names": {"en": "D", "ja": "D"},
                "codes": {"rxnorm": "", "yj": {"oral": "1234567890AB", "injection": ""}},
            }
        }
    }
    rec = _parse_catalog(data)["d"]
    assert "rxnorm" not in rec.codes
    assert rec.codes["yj"] == "1234567890AB"
    assert rec.yj_by_route == {"oral": "1234567890AB"}


def test_parse_catalog_rejects_a_yj_code_without_a_route_class():
    """``codes.yj`` maps a route class to a YJ product (Issue #2347)."""
    data = {"drugs": {"d": {"names": {"en": "D", "ja": "D"}, "codes": {"yj": "1234567890AB"}}}}
    with pytest.raises(ValueError, match="route class"):
        _parse_catalog(data)


# ---------------------------------------------------------------------------
# Integrity: every code pointer resolves against its authority table
# ---------------------------------------------------------------------------


def test_every_rxnorm_pointer_resolves_against_rxnorm_yaml():
    """Every ``codes.rxnorm`` in drugs.yaml must identify a RxCUI that
    exists in ``clinosim/codes/data/rxnorm.yaml``. A dangling pointer is
    a catalog defect, not a runtime fallback case."""
    rxnorm_system = _load_system("rxnorm")
    assert rxnorm_system is not None, "rxnorm.yaml must load for this invariant"
    dangling: list[tuple[str, str]] = []
    for drug_id in all_drug_ids():
        rec = resolve_drug(drug_id)
        rxcui = rec.codes.get("rxnorm")
        if rxcui and rxcui not in rxnorm_system.codes:
            dangling.append((drug_id, rxcui))
    assert not dangling, (
        f"{len(dangling)} drugs.yaml rows carry a codes.rxnorm pointer that is not in rxnorm.yaml: {dangling}"
    )


def test_every_yj_pointer_resolves_against_yj_yaml():
    yj_system = _load_system("yj")
    assert yj_system is not None, "yj.yaml must load for this invariant"
    dangling: list[tuple[str, str]] = []
    for drug_id in all_drug_ids():
        rec = resolve_drug(drug_id)
        yj = rec.codes.get("yj")
        if yj and yj not in yj_system.codes:
            dangling.append((drug_id, yj))
    assert not dangling, f"{len(dangling)} drugs.yaml rows carry a codes.yj pointer that is not in yj.yaml: {dangling}"


def test_every_hot7_pointer_resolves_against_hot7_yaml():
    hot7_system = _load_system("hot7")
    if hot7_system is None:
        pytest.skip("hot7.yaml not present")
    dangling: list[tuple[str, str]] = []
    for drug_id in all_drug_ids():
        rec = resolve_drug(drug_id)
        hot7 = rec.codes.get("hot7")
        if hot7 and hot7 not in hot7_system.codes:
            dangling.append((drug_id, hot7))
    assert not dangling, (
        f"{len(dangling)} drugs.yaml rows carry a codes.hot7 pointer that is not in hot7.yaml: {dangling}"
    )


# ---------------------------------------------------------------------------
# yaml-level uniqueness: pyyaml silently takes the last duplicate key, so
# the only way to catch a duplicated drug_id is a byte-level scan.
# ---------------------------------------------------------------------------


def test_drug_ids_are_unique_in_yaml_source():
    """Scan the yaml source line-by-line for duplicate top-level drug
    keys. pyyaml would silently merge them during parse; this catches
    the author error before it hides a shadowed entry."""
    path = Path(__file__).resolve().parents[2] / "clinosim" / "codes" / "data" / "drugs.yaml"
    text = path.read_text(encoding="utf-8")
    # top-level drug keys are 2-space-indented under the `drugs:` block
    # and match the shape `  <snake_case>:` (no further indentation).
    seen: list[str] = []
    in_drugs_block = False
    for line in text.splitlines():
        if line.rstrip() == "drugs:":
            in_drugs_block = True
            continue
        if not in_drugs_block:
            continue
        if line.startswith("  ") and not line.startswith("    "):
            # key line
            key_part = line.strip()
            if key_part.endswith(":"):
                seen.append(key_part[:-1])
    dups = [k for k in seen if seen.count(k) > 1]
    assert not dups, f"drugs.yaml carries duplicate drug_id keys: {sorted(set(dups))}"


def test_drug_ids_are_snake_case():
    bad = [d for d in all_drug_ids() if d != d.lower() or " " in d or "-" in d]
    assert not bad, f"drug_ids must be snake_case lower: {bad}"


# ---------------------------------------------------------------------------
# Loader caches on the real file so each test here sees the shipped yaml.
# This test confirms the cache is observable to callers (identity invariant).
# ---------------------------------------------------------------------------


def test_catalog_is_cached_singleton():
    first = _load_catalog()
    second = _load_catalog()
    assert first is second
