"""Medication order / MAR / chronic-monitoring per-day generators (Issue #552 PR C).

Extracted verbatim from ``clinosim/simulator/inpatient.py`` — no logic
changes. Groups the 3 standalone medication-related producers into one
topic module.

Public per-day API (called from `inpatient.py::_run_daily_loop` and from
`unknown_condition.py::_simulate_unknown_condition`):

* ``_generate_home_medication_orders`` — home meds (chronic condition
  continuation). Uses `patient.current_medications` as the single source
  of truth (Issue #432) with disease-protocol holds + renal dose
  adjustment applied on top.
* ``_place_chronic_monitoring_orders`` — additional labs for chronic
  condition monitoring (daily / q3d / tid / qid schedules).
* ``_generate_mar`` — MedicationAdministration records for placed
  medication orders (STAT sepsis first-dose grid preserved verbatim,
  session 45).

These functions consume the master RNG in specific orders; extraction
preserves the byte-neutral contract by moving them verbatim.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import numpy as np

from clinosim.modules.staff.engine import FALLBACK_NURSE_ID, StaffRoster, assign_staff
from clinosim.simulator.helpers import _determine_route
from clinosim.types.encounter import (
    MedicationAdministration,
    Order,
    OrderStatus,
    OrderType,
)
from clinosim.types.patient import PatientProfile


def _generate_home_medication_orders(
    patient: PatientProfile,
    encounter_id: str,
    admission_time: datetime,
    attending_id: str,
    rng: np.random.Generator,
    state: Any = None,
    disease_id: str = "",
    protocol: Any = None,
) -> tuple[list[Order], list[dict]]:
    """Generate medication orders for home meds (chronic condition continuation).

    Returns:
        (medication_orders, chronic_monitoring_specs)
    """
    # Issue #432: `patient.current_medications` (set at population time by
    # `_derive_home_medications`) is the SINGLE SOURCE OF TRUTH for what
    # the patient is actually taking at home. Do NOT re-sample the YAML
    # here — that would let activator pick Warfarin and inpatient pick
    # Apixaban, so the "Home medication (continue)" order would not match
    # the patient's home meds (silent data-drift). YAML is still read for
    # per-condition `monitoring` specs (unaffected by the exclusivity
    # question — monitoring is class-independent add-on labs).
    from clinosim.locale.loader import load_chronic_medications

    chronic_meds = load_chronic_medications()

    orders: list[Order] = []
    monitoring: list[dict] = []
    med_idx = 0

    # Collect monitoring specs from every matching ICD block (unchanged).
    for condition in patient.chronic_conditions:
        code = condition.code
        spec = chronic_meds.get(code) or chronic_meds.get(code.split(".")[0])
        if not spec:
            continue
        for mon in spec.get("monitoring", []):
            monitoring.append(mon)

    # Renal state (used by hold + dose-adjustment logic on current_meds below).
    has_ckd = any(c.code.startswith("N18") for c in patient.chronic_conditions)
    renal_reserve = patient.physiological_profile.renal_reserve if hasattr(patient, "physiological_profile") else 1.0
    initial_renal = state.renal_function if state else renal_reserve
    has_renal_impairment = has_ckd or initial_renal < 0.4

    # Held drug set from disease protocol's medication_holds (YAML-driven,
    # protocol side — unchanged semantics, now applied against current_meds).
    held_drugs: set[str] = set()
    hold_reasons: dict[str, str] = {}
    if protocol and hasattr(protocol, "medication_holds"):
        for hold in protocol.medication_holds or []:
            reason = hold.get("reason", "disease-specific hold")
            for drug in hold.get("drugs", []):
                held_drugs.add(drug.lower())
                hold_reasons[drug.lower()] = reason

    # Iterate the patient's actual home meds (single source of truth).
    # Issue #452 PR 3: read `med.drug_name` explicitly instead of `str(med)`.
    # Issue #442: `med.drug_name` is now bare (dose lives in `med.dose`).
    # Order.display_name stays bare so it matches the protocol-side discharge
    # path; structured dose is plumbed into Order.dose_quantity/dose_unit via
    # enrich_medication_order. clinical_intent re-appends dose for narrative
    # continuity ("Home medication (continue): Amlodipine 5mg").
    from clinosim.modules.order.engine import enrich_medication_order

    for med in getattr(patient, "current_medications", None) or []:
        drug_name = med.drug_name
        if not drug_name:
            continue
        drug_lower = drug_name.lower()
        intent_drug = f"{drug_name} {med.dose}".strip() if med.dose else drug_name
        intent = f"Home medication (continue): {intent_drug}"

        # 1. Protocol-driven disease-specific holds.
        yaml_held = False
        for held_name in held_drugs:
            if held_name in drug_lower:
                yaml_held = True
                break
        if yaml_held:
            continue  # silently skip — not ordered

        # 2. Metformin: renal-function-based hold.
        if "metformin" in drug_lower and (initial_renal < 0.4 or has_renal_impairment):
            continue

        # 3. Renal dose adjustment for CKD patients.
        if has_renal_impairment and renal_reserve < 0.5:
            renal_drugs = ["enoxaparin", "enalapril", "candesartan", "alendronate", "celecoxib"]
            if any(rd in drug_lower for rd in renal_drugs):
                if "celecoxib" in drug_lower:
                    continue  # held
                else:
                    intent += " [dose reduced for renal impairment]"

        order = Order(
            order_id=f"ORD-{encounter_id}-HM-{med_idx:02d}",
            encounter_id=encounter_id,
            patient_id=patient.patient_id,
            order_type=OrderType.MEDICATION,
            order_code="",
            display_name=drug_name,
            urgency="routine",
            clinical_intent=intent,
            ordered_datetime=admission_time + timedelta(minutes=60),
            ordered_by=attending_id,
            status=OrderStatus.PLACED,
            route=med.route,
            frequency=med.frequency.upper() if med.frequency else "",
        )
        if med.dose:
            enrich_medication_order(order, med.dose)
        orders.append(order)
        med_idx += 1

    # `rng` argument is retained for signature/backward compat; the
    # sampling that consumed it now lives in `_derive_home_medications`.
    _ = rng

    return orders, monitoring


def _place_chronic_monitoring_orders(
    monitoring: list[dict],
    patient_id: str,
    day: int,
    admission_time: datetime,
    rng: np.random.Generator,
    encounter_id: str = "",
    ordered_by: str = "",
) -> list[Order]:
    """Place additional lab orders for chronic condition monitoring."""
    orders: list[Order] = []

    for i, mon in enumerate(monitoring):
        freq = mon.get("frequency", "daily")

        # Frequency-based scheduling
        if freq == "every_3_days" and day % 3 != 0:
            continue
        if freq == "qid":
            # Multiple times per day — handled differently (monitoring, not standard lab)
            # Generate separate orders at each time
            times = mon.get("times", [6, 11, 17, 21])
            for t_idx, hour in enumerate(times):
                order_time = datetime(
                    admission_time.year,
                    admission_time.month,
                    admission_time.day,
                    hour,
                    0,
                ) + timedelta(days=day)
                if order_time < admission_time:
                    continue
                orders.append(
                    Order(
                        order_id=f"ORD-{encounter_id}-CM-D{day:02d}-{i:02d}-{t_idx}",
                        encounter_id=encounter_id,
                        patient_id=patient_id,
                        order_type=OrderType.LAB,
                        order_code="",
                        display_name=mon["test"],
                        urgency="routine",
                        clinical_intent=mon.get("intent", f"Chronic monitoring: {mon['test']}"),
                        ordered_datetime=order_time,
                        ordered_by=ordered_by,
                        status=OrderStatus.PLACED,
                    )
                )
            continue

        if freq == "tid":
            times = [8, 14, 20]
            for t_idx, hour in enumerate(times):
                order_time = datetime(
                    admission_time.year,
                    admission_time.month,
                    admission_time.day,
                    hour,
                    0,
                ) + timedelta(days=day)
                if order_time < admission_time:
                    continue
                orders.append(
                    Order(
                        order_id=f"ORD-{encounter_id}-CM-D{day:02d}-{i:02d}-{t_idx}",
                        encounter_id=encounter_id,
                        patient_id=patient_id,
                        order_type=OrderType.LAB,
                        order_code="",
                        display_name=mon["test"],
                        urgency="routine",
                        clinical_intent=mon.get("intent", f"Chronic monitoring: {mon['test']}"),
                        ordered_datetime=order_time,
                        ordered_by=ordered_by,
                        status=OrderStatus.PLACED,
                    )
                )
            continue

        # Default: daily at 06:00
        order_time = datetime(
            admission_time.year,
            admission_time.month,
            admission_time.day,
            6,
            0,
        ) + timedelta(days=day)
        orders.append(
            Order(
                order_id=f"ORD-{encounter_id}-CM-D{day:02d}-{i:02d}",
                encounter_id=encounter_id,
                patient_id=patient_id,
                order_type=OrderType.LAB,
                order_code="",
                display_name=mon["test"],
                urgency="routine",
                clinical_intent=mon.get("intent", f"Chronic monitoring: {mon['test']}"),
                ordered_datetime=order_time,
                ordered_by=ordered_by,
                status=OrderStatus.PLACED,
            )
        )

    return orders


def _generate_mar(
    patient: PatientProfile,
    orders: list[Order],
    day: int,
    admission_time: datetime,
    *,
    department: str = "internal_medicine",
    roster: StaffRoster,
    rng: np.random.Generator,
) -> list[MedicationAdministration]:
    """Generate MAR entries for medication orders on this day."""
    from clinosim.modules.order.engine import enrich_medication_order

    mars: list[MedicationAdministration] = []

    med_orders = [o for o in orders if o.order_type == OrderType.MEDICATION and o.status == OrderStatus.PLACED]
    # Ensure medication orders are enriched (idempotent) so MAR can use structured dose
    for o in med_orders:
        enrich_medication_order(o)
    nurse_id = assign_staff("medication_administration", department, roster, rng).get(
        "administering_nurse", FALLBACK_NURSE_ID
    )

    for order in med_orders:
        drug_name = order.display_name
        # Determine administration times based on drug and route
        route = _determine_route(drug_name, order.clinical_intent)

        # Known frequencies for specific drugs
        q6h_drugs = ["AMPICILLIN", "SULBACTAM", "PIPERACILLIN", "TAZOBACTAM"]
        q8h_drugs = ["MEROPENEM", "CEFTRIAXONE", "CEFTAZIDIME"]
        daily_drugs = ["LEVOFLOXACIN", "ENOXAPARIN", "FUROSEMIDE"]

        drug_upper = drug_name.upper()
        if any(d in drug_upper for d in q6h_drugs):
            admin_hours = [0, 6, 12, 18]  # q6h
        elif any(d in drug_upper for d in q8h_drugs):
            admin_hours = [0, 8, 16]  # q8h
        elif any(d in drug_upper for d in daily_drugs) or route == "SC":
            admin_hours = [8]  # daily
        elif route == "IV":
            admin_hours = [0, 8, 16]  # default IV: q8h
        elif "BID" in drug_upper or "bid" in order.clinical_intent.lower():
            admin_hours = [8, 20]
        else:
            admin_hours = [8, 14, 20]  # TID default for PO

        # Session 45 seed=400 verification finding: Sepsis abx-within-3h
        # target (Surviving Sepsis / JSSCG bundle) was 34% because Day-0
        # first dose waited for the next fixed slot (0/8/16). For STAT
        # urgency (sepsis empirical antibiotics, cardiogenic-shock pressor,
        # anaphylaxis epinephrine, etc.) prepend an ad-hoc dose 30-60min
        # after admission on Day-0 so the empirical response window is
        # respected. Subsequent doses continue on the scheduled q6/8h grid.
        stat_first_dose_time = None
        if day == 0 and str(getattr(order, "urgency", "")).lower() == "stat":
            stat_first_dose_time = admission_time + timedelta(minutes=int(rng.integers(30, 61)))

        scheduled_times = []
        if stat_first_dose_time is not None:
            scheduled_times.append(stat_first_dose_time)

        for hour in admin_hours:
            scheduled = datetime(admission_time.year, admission_time.month, admission_time.day, hour, 0) + timedelta(
                days=day
            )

            if scheduled < admission_time:
                continue
            # Skip the scheduled-grid slot if it is within 90min of the STAT
            # ad-hoc dose to avoid a double administration back-to-back.
            if stat_first_dose_time is not None and abs((scheduled - stat_first_dose_time).total_seconds()) < 5400:
                continue
            scheduled_times.append(scheduled)

        for scheduled in scheduled_times:
            # Determine status
            status = "given"
            hold_reason = None

            # Hold conditions (clinical)
            if "antihypertensive" in drug_name.lower() and hasattr(patient, "baseline_vitals"):
                if patient.baseline_vitals.systolic_bp < 90:
                    status, hold_reason = "held", "SBP < 90"

            # Patient refusal (~1.5%)
            if rng.random() < 0.015:
                status = "refused"

            # Jitter
            actual = scheduled + timedelta(minutes=float(rng.normal(5, 10))) if status == "given" else None

            # Build dose text from structured fields if available, else fall back to display_name
            if order.dose_quantity is not None and order.dose_unit:
                dose_text = f"{order.dose_quantity}{order.dose_unit}"
                if order.frequency:
                    dose_text += f" {order.frequency}"
            else:
                dose_text = order.display_name
            mars.append(
                MedicationAdministration(
                    order_id=order.order_id,
                    drug_name=drug_name,
                    scheduled_datetime=scheduled,
                    actual_datetime=actual,
                    status=status,
                    dose=dose_text,
                    route=order.route or _determine_route(drug_name, order.clinical_intent),
                    administered_by=nurse_id,
                    hold_reason=hold_reason,
                )
            )

    return mars
