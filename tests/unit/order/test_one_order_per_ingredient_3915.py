"""A supportive medication is not ordered when the same ingredient is already
ordered (Issue #3915): a COPD exacerbation stay carries one corticosteroid
order, and no protocol orders a drug both as a first-line drug and as a
supportive line."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from pathlib import Path

import numpy as np
import pytest

import clinosim
from clinosim.codes.drugs import drug_ref
from clinosim.datafiles import load_data_yaml
from clinosim.modules.order.engine import place_admission_orders

pytestmark = pytest.mark.unit

_DISEASES = Path(clinosim.__file__).parent / "modules/disease/reference_data"
_START = datetime(2026, 3, 1, 9)
# The disease-YAML slot place_admission_orders is called with (the inpatient
# simulator passes "japan" for Japan).
_SLOTS = ["us", "japan"]
_CORTICOSTEROIDS = {"prednisone", "prednisolone", "methylprednisolone", "dexamethasone", "hydrocortisone"}


def _orders(protocol: dict, slot: str) -> list:
    return place_admission_orders(protocol, "P1", "E1", _START, slot, np.random.default_rng(0))


@pytest.mark.parametrize("slot", _SLOTS)
def test_copd_exacerbation_has_one_corticosteroid_order(slot: str) -> None:
    protocol = load_data_yaml(_DISEASES / "copd_exacerbation.yaml")
    steroids = [
        o
        for o in _orders(protocol, slot)
        if o.order_type.value == "medication" and drug_ref(o.display_name.split(": ", 1)[-1]) in _CORTICOSTEROIDS
    ]
    assert len(steroids) == 1, [o.display_name for o in steroids]
    assert steroids[0].order_id.endswith("M03")  # the first-line block's drug


@pytest.mark.parametrize("slot", _SLOTS)
def test_supportive_medication_of_an_ordered_ingredient_is_skipped(slot: str) -> None:
    protocol = {
        "drugs": {"first_line": {slot: [{"drug_id": "famotidine", "dose": "20mg IV q12h", "route": "IV"}]}},
        "order_protocols": {
            "admission_orders": {
                "supportive": [
                    {"type": "stress_ulcer_prophylaxis", "detail": "Famotidine 40mg IV daily"},
                    {"type": "antipyretic", "detail": "Acetaminophen 500mg PO q6h PRN"},
                    {"type": "antipyretic", "detail": "Acetaminophen 1000mg IV q6h PRN"},
                ]
            }
        },
    }
    meds = [o for o in _orders(protocol, slot) if o.order_type.value == "medication"]
    assert [drug_ref(o.display_name.split(": ", 1)[-1]) for o in meds] == ["famotidine", "acetaminophen"]


@pytest.mark.parametrize("slot", _SLOTS)
def test_no_protocol_orders_an_ingredient_twice(slot: str) -> None:
    """A supportive order never shares its ingredient with another order. (The
    orders of one first-line spec - loading dose / maintenance / infusion - and a
    first-line IV-to-oral step-down of one drug are the protocol's own sequence.)"""
    duplicates: list[str] = []
    for path in sorted(_DISEASES.glob("*.yaml")):
        by_drug: dict[str, list[str]] = defaultdict(list)
        for o in _orders(load_data_yaml(path), slot):
            if o.order_type.value != "medication":
                continue
            ref = drug_ref(o.display_name.split(": ", 1)[-1])
            if ref:
                by_drug[ref].append(o.order_id.split("-ADM-")[-1].split("-")[0])
        duplicates += [
            f"{path.stem}: {k} {v}" for k, v in by_drug.items() if len(set(v)) > 1 and any(x.startswith("S") for x in v)
        ]
    assert not duplicates, duplicates
