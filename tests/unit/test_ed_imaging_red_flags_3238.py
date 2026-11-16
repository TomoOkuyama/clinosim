"""ED imaging red flags force the study (Issue #3238).

A first headache after 50, immunocompromise or a cancer history makes CT of
the head appropriate in an ED migraine presentation (ACR Appropriateness
Criteria Headache, variant 7); a head injury in a patient on an anticoagulant
warrants CT (NICE NG232 1.5.13). Without a red flag the study keeps its
YAML probability, and the forced study leaves every other draw unchanged.
"""

from __future__ import annotations

import copy
from datetime import datetime

import pytest
from pydantic import ValidationError

from clinosim import determinism
from clinosim.locale.loader import load_demographics
from clinosim.modules.encounter.protocol import (
    EncounterConditionProtocol,
    imaging_red_flag,
    load_encounter_condition,
)
from clinosim.modules.patient.activator import activate_patient
from clinosim.modules.population.engine import PersonRecord
from clinosim.modules.staff.engine import generate_roster
from clinosim.simulator.emergency import _simulate_ed_visit
from clinosim.types.encounter import OrderType
from clinosim.types.patient import ChronicCondition, HomeMedication

pytestmark = pytest.mark.unit

_VISIT = datetime(2026, 1, 18, 14)


def _patient(seed: int, age: int, *, meds: tuple[str, ...] = (), chronic: tuple[str, ...] = ()):
    rng = determinism.default_rng(seed)
    person = PersonRecord(
        person_id=f"T-{seed}",
        household_id="H",
        age=age,
        sex="F",
        date_of_birth=datetime(2026 - age, 1, 1).date(),
    )
    patient = activate_patient(person, rng, load_demographics("US"))
    patient.current_medications = [HomeMedication(drug_name=m) for m in meds]
    patient.chronic_conditions = [ChronicCondition(code=c) for c in chronic]
    return patient


def _ct_spec(condition: str) -> dict:
    return next(s for s in load_encounter_condition(condition)["workup"]["imaging"] if s["test"] == "CT_Head")


def _visit(patient, condition: dict, seed: int):
    rng = determinism.default_rng(1000 + seed)
    roster = generate_roster("medium", "US", determinism.default_rng(7))
    return _simulate_ed_visit(patient, condition, _VISIT, roster, rng, country="US", force_severity="moderate")


def _without_red_flags(name: str) -> dict:
    cond = copy.deepcopy(load_encounter_condition(name))
    for spec in cond["workup"]["imaging"]:
        spec.pop("required_if", None)
    return {"name": name, **cond}


def _imaging(record) -> list[str]:
    return [o.display_name for o in record.orders if o.order_type == OrderType.IMAGING]


def _non_imaging(record) -> list[tuple[str, datetime]]:
    return [(o.display_name, o.ordered_datetime) for o in record.orders if o.order_type != OrderType.IMAGING]


# --- red-flag evaluation ----------------------------------------------------


def test_first_headache_after_fifty_is_a_red_flag() -> None:
    spec = _ct_spec("migraine")
    assert imaging_red_flag(spec, _patient(1, 70), _VISIT)
    assert imaging_red_flag(spec, _patient(1, 70, meds=("Apixaban 5mg",)), _VISIT)
    assert not imaging_red_flag(spec, _patient(1, 30), _VISIT)


def test_age_is_taken_at_the_visit() -> None:
    patient = _patient(1, 49)
    patient.date_of_birth = datetime(1976, 1, 10).date()
    assert imaging_red_flag(_ct_spec("migraine"), patient, _VISIT)


def test_known_migraine_after_fifty_is_not_a_new_onset() -> None:
    assert not imaging_red_flag(_ct_spec("migraine"), _patient(1, 62, chronic=("G43",)), _VISIT)


def test_immunocompromise_and_cancer_are_red_flags_at_any_age() -> None:
    spec = _ct_spec("migraine")
    assert imaging_red_flag(spec, _patient(1, 30, chronic=("B20",)), _VISIT)
    assert imaging_red_flag(spec, _patient(1, 30, chronic=("C50",)), _VISIT)


@pytest.mark.parametrize("condition", ["concussion", "elderly_fall"])
def test_anticoagulant_forces_head_ct_after_head_injury(condition: str) -> None:
    spec = _ct_spec(condition)
    assert imaging_red_flag(spec, _patient(1, 40, meds=("Apixaban 5mg",)), _VISIT)
    assert imaging_red_flag(spec, _patient(1, 40, meds=("Warfarin 5mg",)), _VISIT)
    assert not imaging_red_flag(spec, _patient(1, 40, meds=("Aspirin 81mg",)), _VISIT)
    assert not imaging_red_flag(spec, _patient(1, 40), _VISIT)


def test_a_spec_without_red_flags_never_forces() -> None:
    assert not imaging_red_flag({"test": "CT_Head", "probability": 0.3}, _patient(1, 90), _VISIT)


# --- schema --------------------------------------------------------------------


def _with_imaging(spec: dict) -> dict:
    data = copy.deepcopy(load_encounter_condition("migraine"))
    data["workup"]["imaging"] = [spec]
    return data


def test_unknown_condition_group_is_rejected() -> None:
    with pytest.raises(ValidationError, match="no_such_group"):
        EncounterConditionProtocol.model_validate(
            _with_imaging({"test": "CT_Head", "required_if": [{"conditions": ["no_such_group"]}]})
        )


def test_unknown_drug_class_is_rejected() -> None:
    with pytest.raises(ValidationError, match="anticoagulant.nope"):
        EncounterConditionProtocol.model_validate(
            _with_imaging({"test": "CT_Head", "required_if": [{"medication_classes": ["anticoagulant.nope"]}]})
        )


def test_an_empty_red_flag_is_rejected() -> None:
    with pytest.raises(ValidationError, match="criterion"):
        EncounterConditionProtocol.model_validate(_with_imaging({"test": "CT_Head", "required_if": [{}]}))


# --- ED visit ------------------------------------------------------------------


def test_seventy_year_old_on_apixaban_always_gets_head_ct() -> None:
    cond = {"name": "migraine", **load_encounter_condition("migraine")}
    for seed in range(12):
        record = _visit(_patient(seed, 70, meds=("Apixaban 5mg",)), cond, seed)
        assert "CT_Head" in _imaging(record), seed


def test_thirty_year_old_keeps_the_yaml_probability() -> None:
    cond = {"name": "migraine", **load_encounter_condition("migraine")}
    bare = _without_red_flags("migraine")
    imaged = 0
    for seed in range(20):
        patient = _patient(seed, 30)
        with_flags, without = _visit(patient, cond, seed), _visit(patient, bare, seed)
        assert _imaging(with_flags) == _imaging(without)
        imaged += "CT_Head" in _imaging(with_flags)
    assert 0 < imaged < 20


def test_forced_study_moves_no_other_draw() -> None:
    cond = {"name": "migraine", **load_encounter_condition("migraine")}
    bare = _without_red_flags("migraine")
    for seed in range(12):
        patient = _patient(seed, 70, meds=("Apixaban 5mg",))
        with_flags, without = _visit(patient, cond, seed), _visit(patient, bare, seed)
        assert _non_imaging(with_flags) == _non_imaging(without)
        assert [r.value for r in with_flags.lab_results] == [r.value for r in without.lab_results]
        assert with_flags.encounters[0].discharge_datetime == without.encounters[0].discharge_datetime
