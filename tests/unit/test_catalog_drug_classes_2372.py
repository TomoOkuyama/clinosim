"""Complication context and PRN selection use catalog drug classes (Issue #2372)."""

from __future__ import annotations

import pytest

from clinosim.codes.drugs import all_drug_ids, drug_classes
from clinosim.modules.clinical_course._complication_risk_conditions import DRUG_CLASSES, in_drug_class
from clinosim.simulator.medication_pipeline import prn_category

pytestmark = pytest.mark.unit


def test_every_context_class_selects_catalog_drugs() -> None:
    known = {c for d in all_drug_ids() for c in drug_classes(d)}
    for name, sel in DRUG_CLASSES.items():
        assert sel.get("drugs") or sel.get("classes"), name
        assert set(sel.get("classes", ())) | set(sel.get("exclude_classes", ())) <= known, name
        assert set(sel.get("drugs", ())) <= set(all_drug_ids()), name


@pytest.mark.parametrize(
    ("name", "drug_class", "expected"),
    [
        ("Morphine 2mg IV q4h PRN", "opioid", True),
        ("モルヒネ", "opioid", True),
        ("Codeine", "opioid", True),
        ("Ceftriaxone 1g IV q24h", "antibiotic", True),
        ("Silver sulfadiazine cream", "antibiotic", False),  # topical
        ("Enoxaparin 40mg SC daily", "heparin", False),  # LMWH is not unfractionated heparin
        ("Enoxaparin 40mg SC daily", "anticoagulant", True),
        ("Apixaban 5mg", "therapeutic_anticoagulant", True),
        ("Ondansetron", "opioid", False),
        ("Indomethacin 25mg", "nsaid", True),
        ("Aspirin 81mg PO daily", "nsaid", False),  # antiplatelet dose
        ("Nafamostat", "anticoagulant", False),  # dialysis circuit only
    ],
)
def test_in_drug_class(name: str, drug_class: str, expected: bool) -> None:
    assert in_drug_class(name, drug_class) is expected


def test_prn_category_by_catalog_class() -> None:
    assert prn_category("Acetaminophen") == "non_opioid"
    assert prn_category("Ibuprofen 400mg") == "non_opioid"
    assert prn_category("Morphine") == "opioid"
    assert prn_category("Acetaminophen / Codeine") == "opioid"
    assert prn_category("Lorazepam") == "benzodiazepine"
    assert prn_category("Aspirin 81mg") is None  # antiplatelet dose
    assert prn_category("Ondansetron") is None


def test_no_drug_name_substring_tuples_in_class_logic() -> None:
    """The complication context and PRN selection hold no upper-case
    drug-name lists; they ask the catalog for classes."""
    import re
    from pathlib import Path

    import clinosim

    root = Path(clinosim.__file__).parent
    for rel in (
        "modules/clinical_course/_complication_risk_conditions.py",
        "simulator/daily_loop.py",
        "simulator/medication_pipeline.py",
    ):
        src = (root / rel).read_text(encoding="utf-8")
        for bad in ("MORPHINE", "LORAZEPAM", "CEFTRIAXONE", "HEPARIN", "IBUPROFEN"):
            assert not re.search(rf'"{bad}"', src), (rel, bad)
