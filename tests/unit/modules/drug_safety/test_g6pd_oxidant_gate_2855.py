"""Oxidant drugs are blocked for patients with G6PD deficiency (Issue #2855).

The drug-vs-disease rules used to apply only when chronic medications
were sampled, so an ED or inpatient order of TMP-SMX reached a D55.0
patient. The rules now apply on the order gate and the ED gate too.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from clinosim.modules import drug_safety
from clinosim.simulator.emergency import _ed_medication_skipped
from clinosim.simulator.medication_pipeline import apply_drug_safety_gate_to_orders
from clinosim.types.encounter import Order, OrderStatus, OrderType
from clinosim.types.patient import ChronicCondition, PatientProfile

pytestmark = pytest.mark.unit

_WHEN = datetime(2026, 3, 1, 10, 0)


def _patient(*codes: str) -> PatientProfile:
    p = PatientProfile(patient_id="PT-1", age=30, sex="M")
    p.chronic_conditions = [ChronicCondition(code=c) for c in codes]
    return p


def _order(drug: str) -> Order:
    return Order(
        order_id="ORD-1",
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


@pytest.mark.parametrize(
    ("drug", "rule"),
    [
        ("Trimethoprim/Sulfamethoxazole 160/800mg", "sulfonamide-in-g6pd-deficiency"),
        ("Nitrofurantoin 100mg", "nitrofurantoin-in-g6pd-deficiency"),
    ],
)
def test_oxidant_drugs_match_the_g6pd_rules(drug: str, rule: str) -> None:
    entries = drug_safety.condition_entries(_patient("D55.0").chronic_conditions)
    assert [v.rule_id for v in drug_safety.check_candidate_against_disease_state(drug, entries)] == [rule]


def test_non_oxidant_antibiotic_is_allowed() -> None:
    entries = drug_safety.condition_entries(_patient("D55.0").chronic_conditions)
    assert drug_safety.check_candidate_against_disease_state("Ciprofloxacin 500mg", entries) == []


def test_order_gate_drops_tmp_smx_for_g6pd_patient() -> None:
    patient = _patient("D55.0")
    out = apply_drug_safety_gate_to_orders(
        [_order("Trimethoprim/Sulfamethoxazole 160/800mg")],
        patient=patient,
        encounter_id="ENC-1",
        ordered_datetime=_WHEN,
        already_accepted_meds=[],
        country="us",
    )
    assert [o.display_name for o in out] == []
    assert patient.safety_skip_log[0].verdict.rule_id == "sulfonamide-in-g6pd-deficiency"


def test_order_gate_keeps_tmp_smx_without_g6pd() -> None:
    out = apply_drug_safety_gate_to_orders(
        [_order("Trimethoprim/Sulfamethoxazole 160/800mg")],
        patient=_patient("I10"),
        encounter_id="ENC-1",
        ordered_datetime=_WHEN,
        already_accepted_meds=[],
        country="us",
    )
    assert [o.display_name for o in out] == ["Trimethoprim/Sulfamethoxazole 160/800mg"]


def test_ed_gate_skips_nitrofurantoin_for_g6pd_patient() -> None:
    patient = _patient("D55.0")
    skipped = _ed_medication_skipped(
        "Nitrofurantoin 100mg", patient, ["N39.0"], [], "ENC-1", _WHEN, "uti_uncomplicated", "discharge_rx"
    )
    assert skipped
    assert patient.safety_skip_log[-1].verdict.rule_id == "nitrofurantoin-in-g6pd-deficiency"
