"""A take-home NSAID is gated against the drugs given in the ED visit (Issue #3925)."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from clinosim.codes.hl7_encounter import DischargeDisposition
from clinosim.modules.encounter.protocol import load_encounter_condition
from clinosim.simulator.emergency import _ed_discharge_prescription
from clinosim.types.encounter import Encounter, EncounterType
from clinosim.types.patient import PatientProfile

pytestmark = pytest.mark.unit


def _take_home(i: int, condition: str, given_in_ed: list[str]) -> list[str]:
    patient = PatientProfile(patient_id=f"PT-{i}", age=40, sex="M")
    t0 = datetime(2025, 3, 1, 10, 0)
    enc = Encounter(encounter_id=f"ENC-{i}", patient_id=patient.patient_id)
    enc.encounter_type = EncounterType.EMERGENCY
    enc.admission_datetime = t0
    enc.discharge_datetime = t0 + timedelta(hours=3)
    enc.discharge_disposition = DischargeDisposition.HOME
    rx = _ed_discharge_prescription(
        load_encounter_condition(condition), patient, enc, ["G43.9"], "US", condition, ed_medications=given_in_ed
    )
    return [str(item["drug_name"]) for item in (rx.items if rx else [])]


def test_ed_ketorolac_blocks_a_take_home_naproxen() -> None:
    # migraine.yaml: take-home naproxen at probability 0.5; no acetaminophen alternative declared.
    for i in range(40):
        assert "Naproxen" not in _take_home(i, "migraine", ["Ketorolac 30mg"]), i
    assert any("Naproxen" in _take_home(i, "migraine", []) for i in range(40))


def test_ed_ketorolac_blocks_a_take_home_ibuprofen_and_keeps_the_acetaminophen_alternative() -> None:
    for i in range(40):
        items = _take_home(i, "low_back_pain", ["Ketorolac 30mg"])
        assert "Ibuprofen" not in items, i
    assert any("Acetaminophen" in _take_home(i, "low_back_pain", ["Ketorolac 30mg"]) for i in range(40))


def test_ed_ibuprofen_still_gets_the_take_home_ibuprofen() -> None:
    assert any("Ibuprofen" in _take_home(i, "ankle_sprain", ["Ibuprofen 400mg"]) for i in range(40))
