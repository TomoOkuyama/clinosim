"""An ED dose of a drug the patient already takes is a re-dose, not an
interaction (Issue #3310): a patient on daily aspirin presenting with
suspected ACS still gets the aspirin load, while a different NSAID is still
held back by the NSAID-stacking rule."""

from __future__ import annotations

from datetime import datetime

import pytest

from clinosim.simulator.emergency import _ed_medication_skipped
from clinosim.types.patient import PatientProfile

pytestmark = pytest.mark.unit

_WHEN = datetime(2026, 1, 18, 14)


def _skipped(drug: str, active: list[str], hint: str = "ed_treatment") -> tuple[bool, PatientProfile]:
    patient = PatientProfile(patient_id="P1", age=64, sex="M")
    return (
        _ed_medication_skipped(
            drug,
            patient,
            ["R07.9"],
            active,
            "ENC-1",
            _WHEN,
            "chest_pain_noncardiac",
            hint,
            same_drug_reorder=hint == "ed_treatment",
        ),
        patient,
    )


def test_aspirin_load_is_given_to_a_patient_on_daily_aspirin() -> None:
    skipped, patient = _skipped("Aspirin 325mg", ["Aspirin 81mg"])
    assert not skipped
    assert patient.safety_skip_log == []


def test_another_nsaid_is_still_held_back_for_a_patient_on_aspirin() -> None:
    skipped, patient = _skipped("Ketorolac 30mg", ["Aspirin 81mg"])
    assert skipped
    assert patient.safety_skip_log[-1].verdict.rule_id == "nsaid-stacking"


def test_a_take_home_script_still_sees_the_home_drug() -> None:
    """Reconciliation of a duplicate home drug is not an ED re-dose."""
    skipped, _ = _skipped("Aspirin 81mg", ["Aspirin 81mg"], hint="ed_discharge_rx")
    assert skipped
