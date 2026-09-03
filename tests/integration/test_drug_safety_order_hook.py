"""Integration: warfarin patient + NSAID first_line drug → NSAID skipped,
Acetaminophen substituted, safety_skip_log populated."""

from __future__ import annotations

from datetime import datetime

from clinosim.modules.drug_safety.verdict import SafetySkipEntry
from clinosim.simulator.medication_pipeline import (
    apply_drug_safety_gate_to_admission_orders,
)
from clinosim.types.encounter import Order, OrderStatus, OrderType
from clinosim.types.patient import HomeMedication, PatientProfile


def _order(drug: str, order_id: str) -> Order:
    return Order(
        order_id=order_id,
        encounter_id="ENC-1",
        patient_id="PT-1",
        order_type=OrderType.MEDICATION,
        order_code="",
        display_name=drug,
        urgency="routine",
        clinical_intent=f"First-line: {drug}",
        ordered_datetime=datetime(2026, 1, 1, 10, 0),
        ordered_by="DR-1",
        status=OrderStatus.PLACED,
    )


def _patient_with_home_meds(*home_drugs: str) -> PatientProfile:
    p = PatientProfile(patient_id="PT-1")
    for d in home_drugs:
        p.current_medications.append(HomeMedication(drug_name=d))
    return p


def test_gate_drops_ibuprofen_and_substitutes_acetaminophen() -> None:
    """warfarin (home) + Ibuprofen (first_line) → substituted with Acetaminophen."""
    patient = _patient_with_home_meds("Warfarin")
    admission_orders = [_order("Ibuprofen", "ORD-ENC-1-ADM-M01")]

    result = apply_drug_safety_gate_to_admission_orders(
        admission_orders,
        patient,
        encounter_id="ENC-1",
        admission_time=datetime(2026, 1, 1, 10, 0),
        attending_id="DR-1",
        country="us",
    )
    # Ibuprofen dropped; Acetaminophen substitute emitted in its place
    drug_names = [o.display_name for o in result]
    assert "Ibuprofen" not in drug_names
    assert "Acetaminophen" in drug_names
    # safety_skip_log populated
    assert len(patient.safety_skip_log) == 1
    entry = patient.safety_skip_log[0]
    assert entry.candidate_drug == "Ibuprofen"
    assert entry.active_conflict == "Warfarin"
    assert entry.substituted_with == "Acetaminophen"
    assert entry.encounter_id == "ENC-1"


def test_gate_drops_aspirin_when_warfarin_home_med() -> None:
    """warfarin (home) + Aspirin (first_line) → skip Aspirin, no NSAID alternative
    (pain_management → Acetaminophen is safe)."""
    patient = _patient_with_home_meds("Warfarin")
    admission_orders = [_order("Aspirin", "ORD-ENC-1-ADM-M01")]

    result = apply_drug_safety_gate_to_admission_orders(
        admission_orders,
        patient,
        encounter_id="ENC-1",
        admission_time=datetime(2026, 1, 1, 10, 0),
        attending_id="DR-1",
        country="us",
    )
    drug_names = [o.display_name for o in result]
    assert "Aspirin" not in drug_names
    # Aspirin has substitution_hint=pain_management → Acetaminophen
    assert "Acetaminophen" in drug_names
    assert len(patient.safety_skip_log) == 1
    assert patient.safety_skip_log[0].substituted_with == "Acetaminophen"


def test_gate_leaves_safe_pair_untouched() -> None:
    patient = _patient_with_home_meds("Amlodipine")
    admission_orders = [_order("Acetaminophen", "ORD-ENC-1-ADM-M01")]

    result = apply_drug_safety_gate_to_admission_orders(
        admission_orders,
        patient,
        encounter_id="ENC-1",
        admission_time=datetime(2026, 1, 1, 10, 0),
        attending_id="DR-1",
        country="us",
    )
    assert [o.display_name for o in result] == ["Acetaminophen"]
    assert patient.safety_skip_log == []


def test_gate_moderate_severity_attaches_caution_note() -> None:
    """acei_arb + K-sparing diuretic (moderate) → keep order + attach note."""
    patient = _patient_with_home_meds("Candesartan")  # ARB (acei_arb + arb + antihypertensive)
    admission_orders = [_order("Spironolactone", "ORD-ENC-1-ADM-M01")]

    result = apply_drug_safety_gate_to_admission_orders(
        admission_orders,
        patient,
        encounter_id="ENC-1",
        admission_time=datetime(2026, 1, 1, 10, 0),
        attending_id="DR-1",
        country="jp",
    )
    assert [o.display_name for o in result] == ["Spironolactone"]
    # No skip entry — moderate severity is emit_with_note
    assert patient.safety_skip_log == []
    order = result[0]
    notes = getattr(order, "notes", None)
    if notes:
        assert any("併用注意" in n["text"] for n in notes)
    else:
        # Order dataclass may not carry notes yet — Task 11 wires it.
        # In that fallback we stash caution in clinical_intent.
        assert "safety:" in (order.clinical_intent or "")


def test_gate_passes_non_medication_orders_through() -> None:
    patient = _patient_with_home_meds("Warfarin")
    lab_order = Order(
        order_id="ORD-ENC-1-ADM-L01",
        encounter_id="ENC-1",
        patient_id="PT-1",
        order_type=OrderType.LAB,
        order_code="6301-6",
        display_name="PT_INR",
        urgency="routine",
        clinical_intent="INR monitoring",
        ordered_datetime=datetime(2026, 1, 1, 10, 0),
        ordered_by="DR-1",
        status=OrderStatus.PLACED,
    )
    result = apply_drug_safety_gate_to_admission_orders(
        [lab_order, _order("Ibuprofen", "ORD-ENC-1-ADM-M01")],
        patient,
        encounter_id="ENC-1",
        admission_time=datetime(2026, 1, 1, 10, 0),
        attending_id="DR-1",
        country="us",
    )
    # Lab order passes through unchanged; ibuprofen gets substituted
    order_types = [o.order_type for o in result]
    assert OrderType.LAB in order_types
    drug_names = [o.display_name for o in result if o.order_type == OrderType.MEDICATION]
    assert "Ibuprofen" not in drug_names
    assert "Acetaminophen" in drug_names


def test_gate_fully_skips_when_no_alternative_available() -> None:
    """acei_arb + K supplement is major severity, substitution_hint=None → fully skip."""
    patient = _patient_with_home_meds("Enalapril")  # ACEi
    admission_orders = [_order("Potassium chloride", "ORD-ENC-1-ADM-M01")]

    result = apply_drug_safety_gate_to_admission_orders(
        admission_orders,
        patient,
        encounter_id="ENC-1",
        admission_time=datetime(2026, 1, 1, 10, 0),
        attending_id="DR-1",
        country="us",
    )
    drug_names = [o.display_name for o in result]
    assert "Potassium chloride" not in drug_names
    # No substitute in place — fully skipped
    assert len(patient.safety_skip_log) == 1
    entry: SafetySkipEntry = patient.safety_skip_log[0]
    assert entry.substituted_with is None
    assert entry.candidate_drug == "Potassium chloride"
