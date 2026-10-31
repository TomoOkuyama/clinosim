"""CKD stage 4-5 rules fire on the stored CKD representation (Issue #2282).

Chronic CKD is stored as the base code ``N18`` with the stage carried
separately ("CKD G1" .. "CKD G5").
"""

from __future__ import annotations

import pytest

from clinosim.eval.axes.clinical import _CONDITION_LAB_PAIRINGS, _condition_matches_pairing
from clinosim.modules.diagnosis.lab_derived_dx import is_ckd_stage_4_5_carrier
from clinosim.modules.drug_safety.engine import check_candidate_against_disease_state
from clinosim.types.patient import ChronicCondition

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(("stage", "flagged"), [("CKD G4", True), ("CKD G5", True), ("CKD G3a", False)])
def test_nsaid_contraindicated_in_ckd_stage_4_5(stage: str, flagged: bool) -> None:
    # The activator passes (code, stage) tuples (patient/activator.py).
    verdicts = check_candidate_against_disease_state("Ibuprofen", [("N18", stage)])
    assert any(v.rule_id == "nsaid-in-ckd-stage-4-5-by-stage" for v in verdicts) is flagged


@pytest.mark.parametrize(
    ("chronic", "carrier"),
    [
        ([ChronicCondition(code="N18", stage="CKD G5")], True),
        ([ChronicCondition(code="N18", stage="CKD G4")], True),
        ([ChronicCondition(code="N18", stage="CKD G3b")], False),
        ([ChronicCondition(code="N18.5")], True),
        (["N18"], False),
    ],
)
def test_lab_derived_dx_ckd_stage_4_5_exclusion(chronic: list, carrier: bool) -> None:
    assert is_ckd_stage_4_5_carrier(chronic) is carrier


def test_eval_ckd_pairing_matches_emitted_staged_conditions() -> None:
    pairing = next(p for p in _CONDITION_LAB_PAIRINGS if p.name == "ckd_stage_creatinine")
    staged = {"code": {"coding": [{"code": "N18.9"}]}, "stage": [{"summary": {"text": "CKD G4"}}]}
    early = {"code": {"coding": [{"code": "N18.9"}]}, "stage": [{"summary": {"text": "CKD G2"}}]}
    assert _condition_matches_pairing(staged, pairing)
    assert not _condition_matches_pairing(early, pairing)
