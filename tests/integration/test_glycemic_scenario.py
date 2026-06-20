"""Integration tests: disease scenarios that imply poor chronic glycemic control
(DKA) drive HbA1c high via the data-driven chronic_glycemic_control protocol field,
even for a patient with no prior diabetes diagnosis (new-onset DKA)."""

import pytest

pytestmark = pytest.mark.integration


def test_dka_protocol_declares_poor_chronic_control() -> None:
    from clinosim.modules.disease.protocol import load_disease_protocol

    p = load_disease_protocol("diabetic_ketoacidosis")
    assert p.chronic_glycemic_control is not None
    assert p.chronic_glycemic_control <= 0.2  # poor chronic control


def test_dka_forces_high_hba1c_even_without_diabetes_history() -> None:
    from clinosim.modules.disease.protocol import load_disease_protocol
    from clinosim.modules.physiology.engine import derive_lab_values
    from clinosim.types.clinical import PhysiologicalState

    p = load_disease_protocol("diabetic_ketoacidosis")
    # Simulate the inpatient override: patient has no E11 history (glycemic_control None),
    # the scenario forces the chronic control level.
    s = PhysiologicalState()
    assert s.glycemic_control is None
    s.glycemic_control = p.chronic_glycemic_control
    hba1c = derive_lab_values(s, sex="M", age=55, has_diabetes=False)["HbA1c"]
    assert hba1c >= 9.0, f"DKA should imply HbA1c >= 9.0, got {hba1c}"
