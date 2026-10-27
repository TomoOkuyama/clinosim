"""ED treat-and-release requires a safe post-treatment reassessment (#2090)."""

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
from clinosim.simulator.emergency import _simulate_ed_visit, ed_release_safe, ed_treatment_response
from clinosim.types.clinical import PhysiologicalState

pytestmark = pytest.mark.unit


def test_treatment_response_halves_symptoms_and_volume_deficit() -> None:
    state = PhysiologicalState(oxygenation_impairment=0.4, pain_level=0.8, volume_status=-0.4, perfusion_status=0.6)
    after = ed_treatment_response(state)
    assert after.oxygenation_impairment == pytest.approx(0.2)
    assert after.pain_level == pytest.approx(0.4)
    assert after.volume_status == pytest.approx(-0.2)
    assert after.perfusion_status > 0.6
    assert state.oxygenation_impairment == 0.4  # input untouched


@pytest.mark.parametrize(
    ("spo2", "sbp", "avpu", "pain", "copd", "safe"),
    [
        (95.0, 120, "A", 3, False, True),
        (90.0, 120, "A", 3, False, False),
        (90.0, 120, "A", 3, True, True),
        (95.0, 85, "A", 3, False, False),
        (95.0, 120, "V", 3, False, False),
        (95.0, 120, "A", 8, False, False),
    ],
)
def test_release_criteria(spo2: float, sbp: int, avpu: str, pain: int, copd: bool, safe: bool) -> None:
    assert ed_release_safe(spo2=spo2, sbp=sbp, avpu=avpu, pain=pain, copd=copd) is safe


def test_hypoxic_ed_patient_is_reassessed_and_observed_until_safe(monkeypatch: pytest.MonkeyPatch) -> None:
    import clinosim.modules.encounter.protocol as protocol_mod

    condition = copy.deepcopy(load_encounter_condition("asthma_attack_mild"))
    condition["initial_state_impact"] = {"moderate": {"oxygenation_impairment": 0.7}}
    monkeypatch.setattr(protocol_mod, "load_encounter_condition", lambda _cid: condition)
    rng = determinism.default_rng(3)
    roster = generate_roster("medium", "US", rng)
    person = PersonRecord(
        person_id="T-1", household_id="H-1", age=40, sex="M", date_of_birth=datetime(1984, 1, 1).date()
    )
    patient = activate_patient(person, rng, load_demographics("US"))
    record = _simulate_ed_visit(patient, condition, datetime(2024, 6, 1, 14, 0), roster, rng, force_severity="moderate")
    vitals = sorted(record.vital_signs, key=lambda v: v.timestamp)
    assert len(vitals) >= 2
    assert vitals[0].spo2 < 92 <= vitals[-1].spo2
    assert vitals[-1].timestamp <= record.encounters[0].discharge_datetime
