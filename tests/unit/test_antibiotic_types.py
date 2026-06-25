"""Unit tests for AntibioticRegimen and canonical ANTIBIOTIC_DRUGS."""
from datetime import datetime

import pytest

from clinosim.modules.antibiotic import ANTIBIOTIC_DRUGS
from clinosim.types.antibiotic import AntibioticRegimen


@pytest.mark.unit
def test_antibiotic_drugs_canonical_tuple():
    assert isinstance(ANTIBIOTIC_DRUGS, tuple)
    assert ANTIBIOTIC_DRUGS == ("Vancomycin", "Piperacillin/Tazobactam", "Ceftriaxone")


@pytest.mark.unit
def test_antibiotic_regimen_defaults():
    r = AntibioticRegimen()
    assert r.regimen_id == ""
    assert r.hai_event_id == ""
    assert r.encounter_id == ""
    assert r.drug_key == ""
    assert r.dose == ""
    assert r.route == ""
    assert r.frequency == ""
    assert r.start_datetime == datetime(1970, 1, 1)
    assert r.duration_days == 0
    assert r.intent == "empirical"


@pytest.mark.unit
def test_antibiotic_regimen_full_construction():
    r = AntibioticRegimen(
        regimen_id="abx-h1-vancomycin",
        hai_event_id="h1",
        encounter_id="enc-1",
        drug_key="Vancomycin",
        dose="1g",
        route="IV",
        frequency="q12h",
        start_datetime=datetime(2026, 1, 10, 8, 0),
        duration_days=14,
        intent="empirical",
    )
    assert r.drug_key == "Vancomycin"
    assert r.duration_days == 14
    assert r.intent == "empirical"
