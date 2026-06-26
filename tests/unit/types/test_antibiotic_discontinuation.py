from datetime import datetime

from clinosim.types.antibiotic import AntibioticRegimen


def test_discontinuation_datetime_defaults_to_none():
    regimen = AntibioticRegimen()
    assert regimen.discontinuation_datetime is None


def test_discontinuation_datetime_can_be_populated():
    dt = datetime(2024, 1, 15, 8, 0)
    regimen = AntibioticRegimen(discontinuation_datetime=dt)
    assert regimen.discontinuation_datetime == dt


def test_discontinuation_datetime_does_not_break_existing_fields():
    regimen = AntibioticRegimen(
        regimen_id="r1",
        drug_key="vancomycin",
        intent="empirical",
    )
    assert regimen.regimen_id == "r1"
    assert regimen.discontinuation_datetime is None
