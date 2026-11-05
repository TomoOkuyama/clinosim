"""Issue #2713: a discharge prescription does not add a drug of a class it already holds."""

from __future__ import annotations

import pytest

from clinosim.modules import drug_safety

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("candidate", "on_rx", "rule"),
    [
        ("Clopidogrel", "Ticagrelor", "p2y12-plus-p2y12"),
        ("Warfarin", "Apixaban", "doac-plus-vka"),
        ("Candesartan", "Lisinopril", "acei-plus-arb"),
        ("Atorvastatin", "Rosuvastatin", "statin-plus-statin"),
    ],
)
def test_the_class_duplicate_is_a_reconciled_conflict(candidate: str, on_rx: str, rule: str) -> None:
    verdicts = drug_safety.check_candidate_against_active(candidate, [on_rx])
    assert rule in {v.rule_id for v in verdicts}
    assert rule in drug_safety.discharge_reconciliation_rules()


def test_an_indication_dependent_combination_is_not_reconciled() -> None:
    verdicts = drug_safety.check_candidate_against_active("Warfarin", ["Aspirin"])
    assert not {v.rule_id for v in verdicts} & drug_safety.discharge_reconciliation_rules()
