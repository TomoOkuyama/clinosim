"""ED vitals take AVPU from the state; clinic visits do not assess it (#2081)."""

from __future__ import annotations

import copy
from datetime import datetime

import pytest

from clinosim import determinism
from clinosim.locale.loader import load_demographics
from clinosim.modules.encounter.protocol import load_encounter_condition
from clinosim.modules.patient.activator import activate_patient
from clinosim.modules.population.engine import PersonRecord
from clinosim.modules.staff.engine import generate_roster
from clinosim.simulator.emergency import _simulate_ed_visit

pytestmark = pytest.mark.unit


def _visit(condition: dict, seed: int = 3) -> list[str]:
    rng = determinism.default_rng(seed)
    roster = generate_roster("medium", "US", rng)
    person = PersonRecord(
        person_id="T-1", household_id="H-1", age=40, sex="M", date_of_birth=datetime(1984, 1, 1).date()
    )
    patient = activate_patient(person, rng, load_demographics("US"))
    record = _simulate_ed_visit(patient, condition, datetime(2024, 6, 1, 14, 0), roster, rng, force_severity="moderate")
    return [v.consciousness_level for v in record.vital_signs]


def test_ed_avpu_reflects_consciousness_impairment(monkeypatch: pytest.MonkeyPatch) -> None:
    import clinosim.modules.encounter.protocol as protocol_mod

    condition = copy.deepcopy(load_encounter_condition("concussion"))
    condition["initial_state_impact"] = {"moderate": {"consciousness_impairment": 0.9}}
    monkeypatch.setattr(protocol_mod, "load_encounter_condition", lambda _cid: condition)
    assert set(_visit(condition)) <= {"P", "U"}


def test_ed_avpu_alert_without_impairment() -> None:
    assert set(_visit(load_encounter_condition("ankle_sprain"))) == {"A"}


def test_clinic_visit_does_not_record_avpu() -> None:
    assert set(_visit(load_encounter_condition("prescription_renewal"))) <= {""}
