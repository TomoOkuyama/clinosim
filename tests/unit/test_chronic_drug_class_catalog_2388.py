"""Chronic-medication drug_class labels and chemotherapy conflict classes are
catalog drug classes (Issue #2388)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

import clinosim
from clinosim.codes.drugs import all_drug_ids, drug_classes

pytestmark = pytest.mark.unit

_ROOT = Path(clinosim.__file__).parent
_KNOWN = {c for d in all_drug_ids() for c in drug_classes(d)}

# Regimen classes whose drugs are not in the catalog yet (trastuzumab,
# leuprolide, cyclophosphamide, gemcitabine; catalog coverage is #2378).
# They match no chronic medication.
_NOT_YET_CATALOGUED = {"her2_antibody", "lhrh_agonist", "alkylator", "gemcitabine"}


def _yaml(rel: str) -> Any:
    return yaml.safe_load((_ROOT / rel).read_text(encoding="utf-8"))


def _entries(node: Any):
    if isinstance(node, dict):
        if "drug_class" in node:
            yield node
        for v in node.values():
            yield from _entries(v)
    elif isinstance(node, list):
        for v in node:
            yield from _entries(v)


def _exclusive(node: Any):
    if isinstance(node, dict):
        yield from node.get("exclusive_classes") or []
        for v in node.values():
            yield from _exclusive(v)


def test_every_drug_class_is_a_catalog_class_of_its_drug() -> None:
    bad = [
        (e.get("drug_id") or e.get("drug"), e["drug_class"])
        for e in _entries(_yaml("locale/shared/chronic_medications.yaml"))
        if e["drug_class"] not in drug_classes(str(e.get("drug_id") or e.get("drug")))
    ]
    assert not bad, bad


def test_exclusive_classes_are_catalog_classes() -> None:
    assert set(_exclusive(_yaml("locale/shared/chronic_medications.yaml"))) <= _KNOWN


def test_chemo_conflict_classes_are_catalog_classes() -> None:
    regimens = _yaml("locale/shared/chemo_regimens.yaml")["regimens"]
    used = {c for r in regimens.values() for c in (r.get("contains_drug_classes") or [])}
    assert used - _NOT_YET_CATALOGUED <= _KNOWN, sorted(used - _NOT_YET_CATALOGUED - _KNOWN)


@pytest.mark.parametrize(
    ("drug_id", "cls"),
    [
        ("insulin_glargine", "insulin.basal"),
        ("tirzepatide", "glp1_agonist"),
        ("capecitabine", "antineoplastic.fluoropyrimidine"),
        ("tamoxifen", "endocrine_therapy.breast"),
        ("naltrexone", "moud"),
    ],
)
def test_catalog_classes(drug_id: str, cls: str) -> None:
    assert cls in drug_classes(drug_id)
