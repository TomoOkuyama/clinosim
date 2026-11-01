"""Inpatient administration interval and default route come from the drug
catalog by drug_id, not from upper-case name lists (Issue #2389)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

import clinosim
from clinosim.codes.drugs import get_drug
from clinosim.simulator.helpers import _determine_route

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("drug_id", "scheduled", "default"),
    [
        ("ampicillin", 6, None),
        ("ampicillin_sulbactam", 6, None),
        ("piperacillin_tazobactam", 6, None),
        ("meropenem", 8, None),
        ("levofloxacin", None, 24),
        ("enoxaparin", None, 24),
        ("furosemide", None, 24),
        ("ceftriaxone", None, None),  # once daily: no override
    ],
)
def test_catalog_intervals(drug_id: str, scheduled: int | None, default: int | None) -> None:
    drug = get_drug(drug_id)
    assert drug is not None
    assert (drug.scheduled_interval_hours, drug.default_interval_hours) == (scheduled, default)


@pytest.mark.parametrize(
    ("name", "intent", "route"),
    [
        ("Ampicillin/Sulbactam 3g", "", "IV"),
        ("Ceftriaxone 1g", "", "IV"),
        ("Vancomycin 1g", "", "IV"),
        ("Piperacillin/Tazobactam 4.5g", "", "IV"),  # missed by the former name list
        ("Cefepime 2g", "", "IV"),
        ("Enoxaparin 40mg", "", "SC"),
        ("Furosemide 40mg", "", "IV"),
        ("Atorvastatin 20mg", "", "PO"),
        ("Escitalopram 10mg", "", "PO"),  # letters inside a name never decide (Issue #2295)
        ("Ceftriaxone 1g", "IM injection", "IM"),
        ("Insulin regular", "SC sliding scale", "SC"),
    ],
)
def test_route(name: str, intent: str, route: str) -> None:
    assert _determine_route(name, intent) == route


def test_no_drug_name_lists_remain() -> None:
    root = Path(clinosim.__file__).parent
    for rel in ("simulator/medication_pipeline.py", "simulator/helpers.py"):
        src = (root / rel).read_text(encoding="utf-8")
        for name in ("AMPICILLIN", "MEROPENEM", "LEVOFLOXACIN", "ENOXAPARIN", "VANCOMYCIN"):
            assert not re.search(rf'"{name}"', src), (rel, name)
