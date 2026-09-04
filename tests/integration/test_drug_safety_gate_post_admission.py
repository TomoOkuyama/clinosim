"""C7b / Issue #1100: drug_safety gate universality — post-admission
Order paths (daily_loop mid-encounter meds, treatment_mods step-up, etc.)
must also route through ``drug_safety.check_pair`` against the
already-accepted med set (home + admission).

Same-encounter residual on the #1087 cohort (6 undeduped pairs) traced
to daily_loop adding meds like Aspirin / Apixaban a few days into an
IMP where B6 prophylaxis had already placed Enoxaparin at admission.
The existing ``apply_drug_safety_gate_to_admission_orders`` only ran on
admission_orders; nothing gated later additions.

This test suite exercises the general helper
``apply_drug_safety_gate_to_orders`` (public alias
``apply_drug_safety_gate``) that accepts an ``already_accepted_meds``
parameter so caller sites (admission, daily_loop, outpatient, …) can
share the same per-order gating logic without duplication.
"""

from __future__ import annotations

from datetime import datetime

from clinosim.simulator.medication_pipeline import (
    apply_drug_safety_gate_to_orders,
)
from clinosim.types.encounter import Order, OrderStatus, OrderType
from clinosim.types.patient import HomeMedication, PatientProfile


def _order(drug: str, order_id: str = "ORD-1") -> Order:
    return Order(
        order_id=order_id,
        encounter_id="ENC-1",
        patient_id="PT-1",
        order_type=OrderType.MEDICATION,
        order_code="",
        display_name=drug,
        urgency="routine",
        clinical_intent=f"post-admission: {drug}",
        ordered_datetime=datetime(2026, 1, 5, 10, 0),
        ordered_by="DR-1",
        status=OrderStatus.PLACED,
    )


def _patient(*home_drugs: str) -> PatientProfile:
    p = PatientProfile(patient_id="PT-1")
    for d in home_drugs:
        p.current_medications.append(HomeMedication(drug_name=d))
    return p


def test_post_admission_aspirin_against_pre_accepted_enoxaparin_is_skipped() -> None:
    """B6 placed Enoxaparin at admission; daily_loop later adds Aspirin.
    The gate must see Enoxaparin in the pre-accepted set and skip Aspirin."""
    patient = _patient()  # no home meds
    new = [_order("Aspirin", "ORD-D4-01")]
    result = apply_drug_safety_gate_to_orders(
        new,
        patient=patient,
        encounter_id="ENC-1",
        ordered_datetime=datetime(2026, 1, 5, 10, 0),
        attending_id="DR-1",
        country="us",
        already_accepted_meds=["Enoxaparin"],
    )
    names = [o.display_name for o in result]
    # Aspirin skipped or substituted; Aspirin as-is must NOT be in output
    assert "Aspirin" not in names, (
        f"post-admission Aspirin should be blocked when Enoxaparin already accepted; got {names}"
    )
    # safety_skip_log records the skip
    assert len(patient.safety_skip_log) == 1
    entry = patient.safety_skip_log[0]
    assert entry.candidate_drug == "Aspirin"
    assert entry.active_conflict == "Enoxaparin"


def test_post_admission_ibuprofen_substituted_with_acetaminophen() -> None:
    """Post-admission NSAID request against active anticoag: same
    substitution path as admission-time gate."""
    patient = _patient()
    new = [_order("Ibuprofen", "ORD-D3-01")]
    result = apply_drug_safety_gate_to_orders(
        new,
        patient=patient,
        encounter_id="ENC-1",
        ordered_datetime=datetime(2026, 1, 4, 10, 0),
        attending_id="DR-1",
        country="us",
        already_accepted_meds=["Warfarin"],
    )
    names = [o.display_name for o in result]
    assert "Ibuprofen" not in names
    assert "Acetaminophen" in names


def test_post_admission_safe_med_passes_through() -> None:
    """A medication that has no conflict with the pre-accepted set
    must pass through unchanged."""
    patient = _patient()
    new = [_order("Atorvastatin", "ORD-D3-01")]
    result = apply_drug_safety_gate_to_orders(
        new,
        patient=patient,
        encounter_id="ENC-1",
        ordered_datetime=datetime(2026, 1, 4, 10, 0),
        attending_id="DR-1",
        country="us",
        already_accepted_meds=["Enoxaparin", "Metformin"],
    )
    names = [o.display_name for o in result]
    assert names == ["Atorvastatin"]
    assert not patient.safety_skip_log


def test_pre_accepted_meds_includes_home_by_default() -> None:
    """When ``already_accepted_meds`` is None (default), the gate seeds
    the active set from ``patient.current_medications`` — matching the
    admission-orders helper's behavior."""
    patient = _patient("Enoxaparin")  # home med
    new = [_order("Aspirin", "ORD-D4-01")]
    result = apply_drug_safety_gate_to_orders(
        new,
        patient=patient,
        encounter_id="ENC-1",
        ordered_datetime=datetime(2026, 1, 5, 10, 0),
        attending_id="DR-1",
        country="us",
        already_accepted_meds=None,
    )
    names = [o.display_name for o in result]
    assert "Aspirin" not in names


def test_admission_helper_still_works_backward_compat() -> None:
    """The pre-C7b ``apply_drug_safety_gate_to_admission_orders`` API
    must remain callable — it now delegates to the general helper."""
    from clinosim.simulator.medication_pipeline import (
        apply_drug_safety_gate_to_admission_orders,
    )

    patient = _patient("Warfarin")
    admission_orders = [_order("Ibuprofen", "ORD-ADM-01")]
    result = apply_drug_safety_gate_to_admission_orders(
        admission_orders,
        patient,
        encounter_id="ENC-1",
        admission_time=datetime(2026, 1, 1, 10, 0),
        attending_id="DR-1",
        country="us",
    )
    names = [o.display_name for o in result]
    assert "Ibuprofen" not in names
    assert "Acetaminophen" in names
