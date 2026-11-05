"""Issue #2623: an ED visit takes place in the emergency department."""

from __future__ import annotations

import dataclasses
from datetime import datetime

import pytest

from clinosim import determinism
from clinosim.locale.loader import load_demographics
from clinosim.modules.encounter.protocol import load_encounter_condition
from clinosim.modules.output.fhir_r4.encounters.encounter import _build_encounter
from clinosim.modules.patient.activator import activate_patient
from clinosim.modules.population.engine import PersonRecord
from clinosim.modules.staff.engine import generate_roster
from clinosim.simulator.emergency import _simulate_ed_visit
from clinosim.types.encounter import EncounterType

pytestmark = pytest.mark.unit

_T = datetime(2024, 6, 1, 14, 0)


def _ed_encounter(country: str = "US"):
    rng = determinism.default_rng(3)
    roster = generate_roster("medium", country, rng)
    person = PersonRecord(
        person_id="T-1", household_id="H-1", age=40, sex="M", date_of_birth=datetime(1984, 1, 1).date()
    )
    patient = activate_patient(person, rng, load_demographics(country))
    record = _simulate_ed_visit(patient, load_encounter_condition("animal_bite"), _T, roster, rng, country=country)
    [enc] = record.encounters
    return enc


def test_an_ed_encounter_is_in_the_emergency_department() -> None:
    enc = _ed_encounter()
    assert enc.encounter_type == EncounterType.EMERGENCY
    assert enc.department_id == "emergency_medicine"
    assert enc.ward_id == "ER"


@pytest.mark.parametrize("country", ["US", "JP"])
def test_an_ed_encounter_is_located_at_the_ed_for_its_stay(country: str) -> None:
    enc = dataclasses.asdict(_ed_encounter(country))
    enc = {k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in enc.items()}
    enc["encounter_type"] = "emergency"
    res = _build_encounter(enc, "T-1", country=country)
    assert res["serviceProvider"] == {"reference": "Organization/dept-emergency-medicine"}
    [loc] = res["location"]
    assert loc["location"]["reference"] == "Location/loc-ward-ER"
    assert loc["location"]["display"] in ("Emergency Room", "救急外来")
    assert loc["status"] == "completed"
    assert loc["period"] == res["period"] == {"start": enc["admission_datetime"], "end": enc["discharge_datetime"]}
