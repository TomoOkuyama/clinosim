"""Issue #3234: an analgesic never stands in for an antiplatelet.

The anticoagulant + antiplatelet rules used to carry the ``pain_management``
hint, and aspirin is dual-classed as an NSAID, so an aspirin or ticagrelor
order blocked by a DOAC was "substituted" with acetaminophen, and low-dose
aspirin in a heart-failure patient was replaced by acetaminophen under the
NSAID-in-heart-failure rule. For an acute coronary syndrome in a patient on
an oral anticoagulant the in-stay orders now follow the same antithrombotic
plan as the discharge prescription (OAC + clopidogrel, aspirin as a short
course).
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from clinosim.modules import drug_safety
from clinosim.modules.disease.protocol import load_disease_protocol
from clinosim.simulator.discharge_rx import limit_triple_antithrombotic
from clinosim.simulator.medication_pipeline import apply_drug_safety_gate_to_orders
from clinosim.types.encounter import Order, OrderStatus, OrderType
from clinosim.types.patient import ChronicCondition, HomeMedication, PatientProfile

pytestmark = pytest.mark.unit

_WHEN = datetime(2026, 3, 1, 10, 0)
_ACS = SimpleNamespace(disease_id="acute_mi", acs_antithrombotic_plan=True)


def _patient(*home: str, conditions: tuple[tuple[str, str], ...] = ()) -> PatientProfile:
    p = PatientProfile(patient_id="PT-1", age=70, sex="M")
    p.current_medications = [HomeMedication(drug_name=d, drug_name_ja=d, dose="", frequency="") for d in home]
    p.chronic_conditions = [ChronicCondition(code=c, stage=s) for c, s in conditions]  # type: ignore[call-arg]
    return p


def _order(i: int, drug: str) -> Order:
    return Order(
        order_id=f"ORD-{i}",
        encounter_id="ENC-1",
        patient_id="PT-1",
        order_type=OrderType.MEDICATION,
        order_code="",
        display_name=drug,
        urgency="routine",
        clinical_intent="test",
        ordered_datetime=_WHEN,
        ordered_by="DR-1",
        status=OrderStatus.PLACED,
    )


def _gate(patient: PatientProfile, *drugs: str, protocol: object = None, country: str = "US") -> list[Order]:
    return apply_drug_safety_gate_to_orders(
        [_order(i, d) for i, d in enumerate(drugs)],
        patient=patient,
        encounter_id="ENC-1",
        ordered_datetime=_WHEN,
        attending_id="DR-1",
        protocol=protocol,
        country=country,
    )


# --- substitution pool -------------------------------------------------------


@pytest.mark.parametrize("drug", ["Aspirin", "Ticagrelor", "Clopidogrel", "Prasugrel"])
def test_the_analgesic_pool_never_substitutes_an_antiplatelet(drug: str) -> None:
    assert drug_safety.suggest_alternative(drug, "pain_management", active_meds=["Apixaban"], country="US") is None


def test_an_analgesic_nsaid_blocked_by_an_anticoagulant_still_gets_acetaminophen() -> None:
    v = drug_safety.check_pair("Ibuprofen", "Apixaban")
    assert v.rule_id == "anticoagulant-plus-nsaid" and v.substitution_hint == "pain_management"
    alt = drug_safety.suggest_alternative("Ibuprofen", v.substitution_hint, active_meds=["Apixaban"], country="US")
    assert alt is not None and alt.drug == "Acetaminophen"


# --- pair rules ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("oac", "antiplatelet", "rule"),
    [
        ("Apixaban", "Aspirin", "doac-plus-aspirin"),
        ("Rivaroxaban", "Aspirin", "doac-plus-aspirin"),
        ("Apixaban", "Ticagrelor", "doac-plus-p2y12"),
        ("Warfarin", "Aspirin", "vka-plus-antiplatelet"),
        ("Warfarin", "Clopidogrel", "vka-plus-antiplatelet"),
    ],
)
def test_an_antiplatelet_with_an_oral_anticoagulant_is_caught_without_an_analgesic_hint(
    oac: str, antiplatelet: str, rule: str
) -> None:
    v = drug_safety.check_pair(antiplatelet, oac)
    assert v.rule_id == rule and v.severity == "contraindicated"
    assert v.substitution_hint is None


# --- drug x disease rules ------------------------------------------------------


@pytest.mark.parametrize(("code", "stage"), [("I50", ""), ("N18", "CKD G4"), ("N18.5", "")])
def test_low_dose_aspirin_is_not_withheld_as_an_nsaid_in_heart_failure_or_advanced_ckd(code: str, stage: str) -> None:
    assert drug_safety.check_candidate_against_disease_state("Aspirin 81mg", [(code, stage)]) == []
    assert drug_safety.check_candidate_against_disease_state("Ibuprofen", [(code, stage)]) != []


def test_aspirin_in_heart_failure_is_ordered_not_replaced_by_acetaminophen() -> None:
    out = _gate(_patient(conditions=(("I50", ""),)), "Aspirin")
    assert [o.display_name for o in out] == ["Aspirin"]


def test_aspirin_blocked_by_a_disease_rule_gets_no_analgesic_substitute() -> None:
    patient = _patient(conditions=(("K74", ""),))
    out = _gate(patient, "Aspirin")
    assert out == []
    assert patient.safety_skip_log[-1].substituted_with is None


# --- in-stay gate --------------------------------------------------------------


def test_outside_an_acs_an_antiplatelet_on_a_doac_is_avoided_with_no_substitute() -> None:
    patient = _patient("Apixaban")
    out = _gate(patient, "Aspirin", "Ticagrelor")
    assert out == []
    assert [e.substituted_with for e in patient.safety_skip_log] == [None, None]


def test_acs_on_a_doac_follows_the_triple_therapy_plan_in_stay() -> None:
    patient = _patient("Apixaban")
    out = _gate(patient, "Aspirin", "Ticagrelor", "Ibuprofen", protocol=_ACS)
    names = [o.display_name for o in out]
    assert names == ["Aspirin", "Clopidogrel", "Acetaminophen"]
    assert out[0].notes, "the kept aspirin carries the short-course caution"
    assert out[1].dose_quantity == 75 and out[1].frequency == "DAILY"
    ticagrelor = next(e for e in patient.safety_skip_log if e.candidate_drug == "Ticagrelor")
    assert ticagrelor.substituted_with == "Clopidogrel"
    assert ticagrelor.active_conflict == "Apixaban"
    assert all(
        e.substituted_with != "Acetaminophen"
        for e in patient.safety_skip_log
        if e.candidate_drug in {"Aspirin", "Ticagrelor"}
    )


def test_acs_on_warfarin_keeps_clopidogrel_with_a_caution() -> None:
    out = _gate(_patient("Warfarin"), "Aspirin", "Clopidogrel", protocol=_ACS, country="JP")
    assert [o.display_name for o in out] == ["Aspirin", "Clopidogrel"]
    assert all(o.notes for o in out)


def test_acs_plan_does_not_override_other_blocks() -> None:
    """A second P2Y12 inhibitor is still a duplicate under the ACS plan."""
    out = _gate(_patient("Apixaban", "Clopidogrel"), "Ticagrelor", protocol=_ACS)
    assert out == []


def test_acute_mi_protocol_declares_the_acs_plan() -> None:
    assert load_disease_protocol("acute_mi").acs_antithrombotic_plan is True
    assert load_disease_protocol("cerebral_infarction").acs_antithrombotic_plan is False


def test_in_stay_and_discharge_antiplatelets_tell_one_story() -> None:
    """The antiplatelets the ACS gate keeps are the ones the discharge
    prescription carries for the same patient."""
    gated = {o.display_name for o in _gate(_patient("Apixaban"), "Aspirin", "Ticagrelor", protocol=_ACS)}
    items = [{"drug_name": n, "dose": "", "duration_days": 365} for n in ("Aspirin", "Ticagrelor")]
    limit_triple_antithrombotic(items, home_medications=["Apixaban"])
    assert gated == {i["drug_name"] for i in items}
