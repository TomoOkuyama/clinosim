"""Psychotic and manic crisis pathway: ED crisis and psychiatric admission (Issue #2148)."""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from clinosim.codes.hl7_encounter import DischargeDisposition
from clinosim.locale.loader import load_demographics
from clinosim.modules.disease.protocol import load_disease_protocol
from clinosim.modules.encounter.protocol import load_encounter_condition
from clinosim.modules.output.fhir_r4.medications.medications import _resolve_medication_concept
from clinosim.modules.population.engine import generate_monthly_events
from clinosim.simulator.emergency import ed_diagnosis_code, ed_disposition
from clinosim.simulator.inpatient import diagnosis_code_for_patient
from clinosim.simulator.phases._ed_slot import ed_severity_restriction

pytestmark = pytest.mark.unit

_ED = "psychotic_manic_crisis"


def _patient(*codes: str) -> SimpleNamespace:
    return SimpleNamespace(chronic_conditions=[SimpleNamespace(code=c) for c in codes])


def test_ed_crisis_for_schizophrenia_or_bipolar() -> None:
    spec = load_encounter_condition(_ED)
    assert sorted(spec["requires_chronic_prefix"]) == ["F20", "F31"]
    assert ed_diagnosis_code(spec, _patient("F20")) == "F20.9"
    assert ed_diagnosis_code(spec, _patient("F31")) == "F31.9"
    assert ed_disposition(spec, "severe") is DischargeDisposition.PSY
    assert ed_disposition(spec, "mild") is DischargeDisposition.HOME
    assert ed_severity_restriction(spec, frozenset({"psychiatry"}))[0] == ("mild",)


@pytest.mark.parametrize(("country", "code"), [("US", "5093"), ("JP", "1179404")])
def test_haloperidol_codes(country: str, code: str) -> None:
    concept, _ = _resolve_medication_concept("Haloperidol 5mg", order_code="", country=country)
    assert concept["coding"][0]["code"] == code


def test_admission_protocol() -> None:
    protocol = load_disease_protocol("psychosis_inpatient")
    assert protocol.department == "psychiatry" and protocol.state_based_discharge is False
    assert diagnosis_code_for_patient(protocol, _patient("F31"), "F20.9") == "F31.9"
    assert diagnosis_code_for_patient(protocol, _patient("F20"), "F20.9") == "F20.9"


class _Registry:
    def __init__(self, persons: list) -> None:
        self.persons = {p.person_id: p for p in persons}


def _person(pid: str, chronic: list[str]) -> SimpleNamespace:
    return SimpleNamespace(
        person_id=pid,
        age=35,
        sex="M",
        is_alive=True,
        is_alive_at=lambda _d: True,
        chronic_conditions=chronic,
        hospitalization_history=[],
        occupation="other",
        smoking_status="never",
        bmi=23.0,
        care_seeking_threshold=0.5,
    )


@pytest.mark.parametrize("country", ["US", "JP"])
def test_admissions_need_the_psychiatric_ward(country: str) -> None:
    spec = load_demographics(country)["disease_incidence"]["psychosis_inpatient"]
    assert spec["requires_inpatient_ward"] == "psychiatry"
    demo = {"disease_incidence": {"psychosis_inpatient": {**spec, "age_rates": {18: 10_000_000}}}}
    reg = _Registry([_person("A", ["F20"]), _person("B", ["F31"]), _person("C", ["F32"])])

    def count(depts: frozenset[str]) -> int:
        events = generate_monthly_events(
            reg, 2024, 3, np.random.default_rng(1), demo=demo, master_seed=5, inpatient_departments=depts
        )
        return sum(e.disease_id == "psychosis_inpatient" for e in events)

    assert count(frozenset({"psychiatry"})) == 2
    assert count(frozenset({"internal_medicine"})) == 0
