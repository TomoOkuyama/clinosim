"""Issue #3003: heparin with low-dose antiplatelet aspirin is the standard
acute-coronary-syndrome regimen, so the anticoagulant + NSAID bleeding rule
does not avoid heparin (or enoxaparin) because of aspirin. Analgesic NSAIDs
with heparin, and aspirin with an oral anticoagulant, are still caught."""

from __future__ import annotations

import pytest

from clinosim.modules import drug_safety

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("anticoagulant", ["Heparin", "Enoxaparin"])
def test_heparin_is_not_avoided_because_of_aspirin(anticoagulant: str) -> None:
    assert drug_safety.check_pair(anticoagulant, "Aspirin").is_allowed
    assert drug_safety.check_pair("Aspirin", anticoagulant).is_allowed
    assert drug_safety.check_candidate_against_active(anticoagulant, ["Aspirin", "Clopidogrel"]) == []


@pytest.mark.parametrize("nsaid", ["Ibuprofen", "Loxoprofen", "Celecoxib", "Ketorolac"])
def test_heparin_with_an_analgesic_nsaid_is_still_avoided(nsaid: str) -> None:
    v = drug_safety.check_pair("Heparin", nsaid)
    assert v.severity == "contraindicated" and v.rule_id == "anticoagulant-plus-nsaid"


@pytest.mark.parametrize(("anticoagulant", "rule"), [("Apixaban", "anticoagulant-plus-nsaid"), ("Warfarin", None)])
def test_aspirin_with_an_oral_anticoagulant_is_still_caught(anticoagulant: str, rule: str | None) -> None:
    v = drug_safety.check_pair(anticoagulant, "Aspirin")
    assert v.severity == "contraindicated"
    if rule:
        assert v.rule_id == rule


def test_a_patient_on_heparin_gets_no_second_heparin() -> None:
    """With heparin given beside aspirin, DVT-prophylaxis enoxaparin is not
    added to therapeutic heparin."""
    v = drug_safety.check_pair("Enoxaparin", "Heparin")
    assert v.severity == "contraindicated" and v.rule_id == "heparin-plus-heparin"
