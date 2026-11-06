"""Issue #2786: both monitoring paths read one drug -> monitoring-lab table."""

from __future__ import annotations

import pytest

from clinosim.modules.monitoring.engine import load_medication_lab_mapping
from clinosim.modules.monitoring.mapping import load_medication_monitoring

pytestmark = pytest.mark.unit


def _pairs(table: dict, labs_of) -> set[tuple[str, str]]:
    return {(key, lab) for key, entry in table.items() for lab in labs_of(entry)}


def test_both_paths_list_the_same_drug_lab_pairs() -> None:
    follow_up = _pairs(load_medication_lab_mapping(), lambda e: e["labs"])
    enricher = _pairs(load_medication_monitoring(), lambda e: [m["lab"] for m in e["monitoring"]])
    assert follow_up == enricher


@pytest.mark.parametrize(
    ("key", "lab"),
    [("Apixaban", "eGFR"), ("Digoxin", "Digoxin"), ("Tacrolimus", "Tacrolimus"), ("Valproic acid", "ALT")],
)
def test_entries_once_on_one_path_only_are_on_both(key: str, lab: str) -> None:
    assert lab in load_medication_lab_mapping()[key]["labs"]
    assert lab in [m["lab"] for m in load_medication_monitoring()[key]["monitoring"]]
