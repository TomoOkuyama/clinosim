"""Issue #4026: clinosim ships only the YJ codes it uses.

``clinosim.codes.yj.is_verified_yj`` used to read the complete YJ CodeSystem
(``JP_MedicationCodeYJ_CS_full.json``, 23,923 concepts built from the MEDIS
医薬品HOTコードマスター) only to build a set of code strings. It now reads
``codes/authoritative/yj_medis_hot_used.json``: the codes of that
master which the YJ registry (``codes/data/yj.yaml``) holds, with the names
``yj.yaml`` already curates.

The guard: every YJ code the drug catalog or the registry can emit is in the
subset, the subset holds nothing else and copies no text beyond ``yj.yaml``,
and the codes the full file did not list are still unverified. How to verify
a new code against the MEDIS master is documented in
``clinosim/codes/authoritative/README.md`` ("Verifying a new YJ code").
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from clinosim.codes.drugs import all_drug_ids, resolve_drug
from clinosim.codes.yj import _verified_yj_codes, is_verified_yj

pytestmark = pytest.mark.unit

_CODES_DIR = Path(__file__).resolve().parents[3] / "clinosim" / "codes"
_SUBSET = _CODES_DIR / "authoritative" / "yj_medis_hot_used.json"

# Every 12-character YJ-shaped string in the repository that the removed full
# file did NOT list, recorded before it was removed (Issue #4026). Comments of
# drugs.yaml quote four MHLW drug-price-list codes (統一名収載); tests and
# docs quote the others as examples of codes outside the master.
_NOT_IN_MASTER = (
    "1147002F1013",
    "1179040F1012",
    "2115001X1015",
    "2129005F1013",
    "2149032F1013",
    "2149039F1022",
    "2149400A1019",
    "2190400A2011",
    "2190400A5010",
    "2242001B2017",
    "2355002X1016",
    "2414402A1019",
    "2431004F1013",
    "2451400A1013",
    "2451401A1018",
    "3213001X1010",
    "3221001F1032",
    "3319400A2039",
    "3319539A1015",
    "3999018F1013",
    "4291013F1029",
    "6113005F1023",
    "6322400X2013",
)


def _subset() -> dict:
    return json.loads(_SUBSET.read_text(encoding="utf-8"))


def _registry() -> dict[str, dict[str, str]]:
    return yaml.safe_load((_CODES_DIR / "data" / "yj.yaml").read_text(encoding="utf-8"))["codes"]


def _catalog_yj_codes() -> set[str]:
    return {code for drug_id in all_drug_ids() for code in resolve_drug(drug_id).yj_by_route.values()}


def test_full_code_system_is_not_shipped() -> None:
    assert not (_CODES_DIR / "authoritative" / "JP_MedicationCodeYJ_CS_full.json").exists()


def test_subset_records_its_master_edition() -> None:
    meta = _subset()["metadata"]
    assert meta["source_file"] == "MEDIS20260831.TXT"
    assert meta["edition"] == "2026.8.31"
    assert meta["fetched"] is None  # the removed file recorded no fetch date
    assert meta["verify_new_code"]


def test_every_catalog_and_registry_code_is_in_the_subset() -> None:
    subset = {c["code"] for c in _subset()["concept"]}
    missing = sorted((_catalog_yj_codes() | set(_registry())) - subset)
    assert not missing, (
        f"YJ codes not in {_SUBSET.name}: {missing}. Verify each against the MEDIS master "
        "(clinosim/codes/authoritative/README.md, 'Verifying a new YJ code') before adding it."
    )


def test_subset_holds_only_registry_codes_and_their_curated_names() -> None:
    registry = _registry()
    concepts = _subset()["concept"]
    codes = [c["code"] for c in concepts]
    assert codes == sorted(set(codes)), "concepts must be unique and sorted by code"
    for c in concepts:
        assert set(c) == {"code", "name"}, c
        assert c["code"] in registry, f"{c['code']} is not a yj.yaml code"
        assert c["name"] == registry[c["code"]]["ja"], c["code"]


def test_gate_answers_match_the_full_file() -> None:
    """The answers recorded from the full file before it was removed: every
    registry code is verified, every code the full file did not list is not."""
    assert _verified_yj_codes() == frozenset(_registry())
    assert all(is_verified_yj(c) for c in _registry())
    assert not any(is_verified_yj(c) for c in _NOT_IN_MASTER)
    assert not is_verified_yj("")
