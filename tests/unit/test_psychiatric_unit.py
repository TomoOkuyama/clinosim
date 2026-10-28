"""Psychiatric unit at the large hospital: depression admissions (Issue #2132)."""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from clinosim.modules.disease.protocol import load_disease_protocol
from clinosim.modules.encounter.protocol import load_encounter_condition
from clinosim.modules.population.engine import generate_monthly_events
from clinosim.simulator._setup import _load_hospital_ops
from clinosim.simulator.hospital_ops import inpatient_departments
from clinosim.simulator.inpatient import diagnosis_code_for_patient
from clinosim.simulator.phases._ed_slot import ed_severity_restriction

pytestmark = pytest.mark.unit

_LARGE = "clinosim/config/hospital_large.yaml"


def test_only_the_large_hospital_has_a_psychiatric_ward() -> None:
    assert "psychiatry" in inpatient_departments(_load_hospital_ops(_LARGE))
    assert "psychiatry" not in inpatient_departments(_load_hospital_ops(None))


class _Registry:
    def __init__(self, persons: list) -> None:
        self.persons = {p.person_id: p for p in persons}


def _person(pid: str, chronic: list[str]) -> SimpleNamespace:
    return SimpleNamespace(
        person_id=pid,
        age=35,
        sex="F",
        is_alive=True,
        is_alive_at=lambda _d: True,
        chronic_conditions=chronic,
        hospitalization_history=[],
        occupation="other",
        smoking_status="never",
        bmi=23.0,
        care_seeking_threshold=0.5,
    )


def _depression_events(depts: frozenset[str] | None) -> int:
    demo = {
        "disease_incidence": {
            "depression_inpatient": {
                "age_rates": {18: 10_000_000},  # certain within a month
                "prerequisite_condition": ["F32", "F33"],
                "requires_inpatient_ward": "psychiatry",
                "event_type": "acute_disease_onset",
                "always_hospitalize": True,
                "rng_isolated": True,
            }
        }
    }
    reg = _Registry([_person("A", ["F32"]), _person("B", ["F33"]), _person("C", ["I10"])])
    events = generate_monthly_events(
        reg, 2024, 3, np.random.default_rng(1), demo=demo, master_seed=5, inpatient_departments=depts
    )
    return sum(e.disease_id == "depression_inpatient" for e in events)


def test_depression_admissions_need_the_psychiatric_ward() -> None:
    assert _depression_events(frozenset({"psychiatry", "internal_medicine"})) == 2  # F32 and F33, not I10
    assert _depression_events(frozenset({"internal_medicine"})) == 0
    assert _depression_events(None) == 0


def test_ed_crisis_keeps_only_discharged_severities_with_a_unit() -> None:
    spec = load_encounter_condition("suicidal_ideation_depression")
    allowed, share = ed_severity_restriction(spec, frozenset({"psychiatry"}))
    assert allowed == ("mild",) and share == pytest.approx(0.30)
    assert ed_severity_restriction(spec, frozenset({"internal_medicine"})) == (None, 1.0)
    assert ed_severity_restriction(load_encounter_condition("ankle_sprain"), frozenset({"psychiatry"})) == (None, 1.0)


def test_recurrent_depression_is_coded_f33() -> None:
    protocol = load_disease_protocol("depression_inpatient")
    f33 = SimpleNamespace(chronic_conditions=[SimpleNamespace(code="F33")])
    f32 = SimpleNamespace(chronic_conditions=[SimpleNamespace(code="F32")])
    assert diagnosis_code_for_patient(protocol, f33, "F32.2") == "F33.2"
    assert diagnosis_code_for_patient(protocol, f32, "F32.2") == "F32.2"
    assert diagnosis_code_for_patient(protocol, f33, "R69") == "R69"  # only the primary code is refined
    assert protocol.department == "psychiatry"


def test_admission_mental_status_exam_is_rendered() -> None:
    from clinosim.modules.document.narrative.renderers._shared_helpers import (
        format_physical_exam,
        pydantic_day_findings_to_dict,
    )

    protocol = load_disease_protocol("depression_inpatient")
    day0 = protocol.narrative.physical_exam_findings["smooth_recovery"]["day_0"]
    text = format_physical_exam(pydantic_day_findings_to_dict(day0), "severe", "ja")
    assert "精神状態" in text and "希死念慮" in text


def test_readmission_respects_minimum_severity() -> None:
    from datetime import datetime

    from clinosim.simulator.discharge_gate import _evaluate_readmission
    from clinosim.types.clinical import PhysiologicalState

    protocol = load_disease_protocol("depression_inpatient")
    record = SimpleNamespace(
        physiological_states=[PhysiologicalState(patient_id="P", inflammation_level=0.0)],
        patient=SimpleNamespace(age=40, chronic_conditions=[]),
        clinical_diagnosis=SimpleNamespace(missed_diagnoses=[]),
        encounters=[SimpleNamespace(discharge_datetime=datetime(2024, 3, 1, 10), encounter_id="E1")],
        readmission_number=0,
    )
    seen = 0
    for seed in range(200):
        event = _evaluate_readmission(
            record, SimpleNamespace(person_id="P"), "depression_inpatient", protocol, "us", np.random.default_rng(seed)
        )
        if event is not None:
            seen += 1
            assert event.severity >= 0.3  # moderate or above (minimum_severity: moderate)
    assert seen


def test_psychiatric_stay_follows_sampled_los_not_physiology() -> None:
    import contextlib
    import io
    from statistics import median

    from clinosim.simulator import run_forced
    from clinosim.types.config import ForcedScenario, SimulatorConfig

    assert load_disease_protocol("depression_inpatient").state_based_discharge is False
    with contextlib.redirect_stdout(io.StringIO()):
        ds = run_forced(
            ForcedScenario(disease_id="depression_inpatient", count=30, severity="moderate"),
            SimulatorConfig(random_seed=3, country="US", catchment_population=30),
        )
    los = [len(r.physiological_states) - 1 for r in ds.patients]
    assert median(los) >= 5  # target mean 6, min 3; physiology alone discharged at day 3
