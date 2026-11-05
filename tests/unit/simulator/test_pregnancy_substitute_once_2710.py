"""Issue #2710: a pregnancy substitute is listed once on a prescription."""

from __future__ import annotations

import pytest

from clinosim.simulator.outpatient import unique_items_by_drug

pytestmark = pytest.mark.unit


def test_two_items_substituted_by_the_same_drug_become_one() -> None:
    items = [
        {"drug_name": "Methyldopa", "dose": "250mg"},
        {"drug_name": "Atorvastatin", "dose": "10mg"},
        {"drug_name": "Methyldopa", "dose": "250mg"},
    ]
    assert [i["drug_name"] for i in unique_items_by_drug(items)] == ["Methyldopa", "Atorvastatin"]
