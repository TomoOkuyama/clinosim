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
).

These functions consume the master RNG in specific orders; extraction
preserves the byte-neutral contract by moving them verbatim.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import numpy as np

from clinosim.modules.physiology.renal_thresholds import (
    METFORMIN_ADMISSION_HOLD_THRESHOLD,
    METFORMIN_RENAL_RESERVE_THRESHOLD,
)
from clinosim.modules.staff.engine import FALLBACK_NURSE_ID, StaffRoster, assign_staff
from clinosim.simulator._mar_thresholds import (
    MAR_ANTIHYPERTENSIVE_HOLD_SBP_THRESHOLD,
    MAR_JITTER_MEAN_MIN,
    MAR_JITTER_STD_MIN,
    MAR_PATIENT_REFUSAL_PROBABILITY,
    MAR_STAT_DUPLICATE_AVOIDANCE_WINDOW_SEC,
    MAR_STAT_FIRST_DOSE_DELAY_MAX_EXCLUSIVE,
    MAR_STAT_FIRST_DOSE_DELAY_MIN,
)
from clinosim.simulator.helpers import _determine_route
from clinosim.types.encounter import (
    MedicationAdministration,
    Order,
    OrderStatus,
    OrderType,
)
from clinosim.types.patient import PatientProfile

# ---------------------------------------------------------------------------
# Issue #913: MedicationAdministration must honour parent
# MedicationRequest.dosageInstruction.timing.repeat.frequency.
#
# Pre-fix the MAR generator used a hardcoded drug-name dispatch (q6h_drugs
# / q8h_drugs / daily_drugs / route heuristics) and ignored
# ``order.frequency_per_day``. MedicationRequest emit derived the timing
# from ``parse_dose_string`` (medications.py line 1183-1187), so amlodipine
# 1/day showed up as MR.timing.frequency=1 but got 3/day MedAdmins from the
# TID default — a 3× on-chart over-dose signature (audit v0.5.0: 60.3 %
# of MR ↔ MA pairs over-admin, 60 % of that being 1/day → 3/day).
#
# Fix: use ``order.frequency_per_day`` when populated. Fall back to the
# drug-name dispatch only when the enricher could not determine a
# frequency (e.g. antibiotics like "Meropenem 1g" whose display_name
# doesn't declare a schedule).
#
# Continuous infusions (freq ≥ 12/day) are capped at Q4H (6/day) to
# reflect the way real nursing charts record MAR entries for continuous
# drips (per-shift check + dose-change annotations) rather than emitting
# hourly rows. Cap is a data-volume compromise, not clinical semantics —
# the prescription still carries ``timing.repeat.frequency=24``; the
# discrepancy shrinks from 8× (audit's 24 → 3 under-admin) to 4× (24 →
# 6), and represents "MAR observed q4h during infusion".
_FREQ_TO_HOURS: dict[int, list[int]] = {
    1: [8],
    2: [8, 20],
    3: [8, 14, 20],
    4: [0, 6, 12, 18],
    5: [6, 10, 14, 18, 22],
    6: [0, 4, 8, 12, 16, 20],
    7: [3, 6, 9, 12, 15, 18, 21],
    8: [0, 3, 6, 9, 12, 15, 18, 21],
}
_CONTINUOUS_INFUSION_MAR_HOURS: list[int] = [0, 4, 8, 12, 16, 20]  # q4h cap for freq >= 12


def _admin_hours_from_frequency(freq_per_day: int) -> list[int]:
    """Map a prescribed per-day frequency (from ``MR.timing.repeat.frequency``
    equivalent) to the MAR admin-hour slots.

    Issue #913: eliminates the divergence between MedicationRequest
    prescription frequency and MedicationAdministration actual admins.
    """
    if freq_per_day <= 0:
        return [8, 14, 20]
    if freq_per_day >= 12:
        return list(_CONTINUOUS_INFUSION_MAR_HOURS)
    if freq_per_day <= 8:
        return list(_FREQ_TO_HOURS[freq_per_day])
    # 9-11: rare (e.g. q2.5h) — snap to q3h (8/day).
    return list(_FREQ_TO_HOURS[8])


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
    has_renal_impairment = has_ckd or initial_renal < METFORMIN_ADMISSION_HOLD_THRESHOLD

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
        # Issue #871: parallel JA display for JP SR reasonCode.text. `intent_drug`
        # includes the raw drug name + dose (which may be EN or JA depending on
        # the source); the shell is translated.
        intent_ja = f"継続内服: {intent_drug}"

        # 1. Protocol-driven disease-specific holds.
        yaml_held = False
        for held_name in held_drugs:
            if held_name in drug_lower:
                yaml_held = True
                break
        if yaml_held:
            continue  # silently skip — not ordered

        # 2. Metformin: renal-function-based hold.
        if "metformin" in drug_lower and (initial_renal < METFORMIN_ADMISSION_HOLD_THRESHOLD or has_renal_impairment):
            continue

        # 3. Renal dose adjustment for CKD patients.
        if has_renal_impairment and renal_reserve < METFORMIN_RENAL_RESERVE_THRESHOLD:
            renal_drugs = ["enoxaparin", "enalapril", "candesartan", "alendronate", "celecoxib"]
            if any(rd in drug_lower for rd in renal_drugs):
                if "celecoxib" in drug_lower:
                    continue  # held
                else:
                    intent += " [dose reduced for renal impairment]"
                    # Issue #871: mirror the annotation on the JA display.
                    intent_ja += " [腎機能低下のため減量]"

        order = Order(
            order_id=f"ORD-{encounter_id}-HM-{med_idx:02d}",
            encounter_id=encounter_id,
            patient_id=patient.patient_id,
            order_type=OrderType.MEDICATION,
            order_code="",
            display_name=drug_name,
            urgency="routine",
            clinical_intent=intent,
            # Issue #871: JA display for JP SR reasonCode.text.
            clinical_intent_ja=intent_ja,
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
                        # Issue #871: JA display for JP SR reasonCode.text.
                        # Reads `intent_ja` from the YAML spec; falls back to
                        # a shell-translated default when the YAML has not
                        # yet been extended.
                        clinical_intent_ja=mon.get("intent_ja", f"慢性モニタリング: {mon['test']}"),
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
                        # Issue #871: JA display for JP SR reasonCode.text.
                        # Reads `intent_ja` from the YAML spec; falls back to
                        # a shell-translated default when the YAML has not
                        # yet been extended.
                        clinical_intent_ja=mon.get("intent_ja", f"慢性モニタリング: {mon['test']}"),
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
                # Issue #871: JA display for JP SR reasonCode.text.
                clinical_intent_ja=mon.get("intent_ja", f"慢性モニタリング: {mon['test']}"),
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

    # Session-98 F4/F5 fix: DISCONTINUE orders describe a treatment
    # STOP event, not an administration. `daily_loop._apply_treatment_modifier`
    # emits them as `Order(order_type=MEDICATION, display_name="DISCONTINUE: X",
    # status=PLACED)` for downstream visibility, but rendering them as
    # MedicationAdministration produces phantom "administrations" with
    # neither dose nor rate (dosage.text = "SC", dose.value absent) — 1,005
    # such MAs on a US p=10000 seed=300 run (Ampicillin/Sulbactam 544,
    # Piperacillin/Tazobactam 324, Ceftriaxone 103; all reported as F4
    # empty-dose AND F5 IV-drug-with-SC-route defects in the session-98
    # extended verify). The FHIR way to represent a stop is
    # `MedicationRequest.status="stopped"` on the parent Rx, NOT a MAR.
    # Filter here so the downstream MAR builder never sees these orders.
    med_orders = [
        o
        for o in orders
        if o.order_type == OrderType.MEDICATION
        and o.status == OrderStatus.PLACED
        and not (o.display_name or "").startswith("DISCONTINUE:")
    ]
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

        # Issue #913: MAR admin count must match
        # ``MedicationRequest.dosageInstruction.timing.repeat.frequency``
        # (both derived from the same order — before this fix, MAR ran
        # on a hardcoded drug-name heuristic that diverged from what the
        # prescription said → 60 % of pairs over-admin, ~3× on-chart
        # over-dose signature).
        #
        # Ordering:
        # 1. Antibiotic clinical-override (Q6H / Q8H) — for β-lactam
        #    combos + carbapenem + advanced cephalosporins whose 1/day
        #    default (from the enricher) would be clinically dangerous.
        #    Ceftriaxone (correctly 1/day) is intentionally omitted.
        # 2. Explicit prescribed frequency (``order.frequency_per_day``) —
        #    honours the parsed prescription frequency, aligning MAR to MR.
        # 3. Legacy drug-name / route dispatch — the enricher's DAILY
        #    default fires for parseable-dose but no-frequency orders,
        #    so this branch is rarely hit today; kept for safety on
        #    orders without a resolvable frequency at all.
        drug_upper = drug_name.upper()
        q6h_drugs = ["AMPICILLIN", "SULBACTAM", "PIPERACILLIN", "TAZOBACTAM"]
        q8h_drugs = ["MEROPENEM", "CEFTAZIDIME"]
        _freq_per_day = getattr(order, "frequency_per_day", None)
        if any(d in drug_upper for d in q6h_drugs):
            admin_hours = [0, 6, 12, 18]  # q6h — clinical override for β-lactam combos
        elif any(d in drug_upper for d in q8h_drugs):
            admin_hours = [0, 8, 16]  # q8h — clinical override for carbapenem / adv ceph
        elif _freq_per_day and _freq_per_day > 0:
            admin_hours = _admin_hours_from_frequency(int(_freq_per_day))
        else:
            # Legacy fallback (unresolvable frequency).
            daily_drugs = ["LEVOFLOXACIN", "ENOXAPARIN", "FUROSEMIDE"]
            if any(d in drug_upper for d in daily_drugs) or route == "SC":
                admin_hours = [8]  # daily
            elif route == "IV":
                admin_hours = [0, 8, 16]  # default IV: q8h
            elif "BID" in drug_upper or "bid" in order.clinical_intent.lower():
                admin_hours = [8, 20]
            else:
                admin_hours = [8, 14, 20]  # TID default for PO

        # seed=400 verification finding: Sepsis abx-within-3h
        # target (Surviving Sepsis / JSSCG bundle) was 34% because Day-0
        # first dose waited for the next fixed slot (0/8/16). For STAT
        # urgency (sepsis empirical antibiotics, cardiogenic-shock pressor,
        # anaphylaxis epinephrine, etc.) prepend an ad-hoc dose 30-60min
        # after admission on Day-0 so the empirical response window is
        # respected. Subsequent doses continue on the scheduled q6/8h grid.
        stat_first_dose_time = None
        if day == 0 and str(getattr(order, "urgency", "")).lower() == "stat":
            stat_first_dose_time = admission_time + timedelta(
                minutes=int(rng.integers(MAR_STAT_FIRST_DOSE_DELAY_MIN, MAR_STAT_FIRST_DOSE_DELAY_MAX_EXCLUSIVE))
            )

        scheduled_times = []
        if stat_first_dose_time is not None:
            scheduled_times.append(stat_first_dose_time)

        # Issue #850: on day 0, when the patient is admitted AFTER every
        # scheduled-hour slot for the day (patient admitted at 16:43 to
        # an IV order whose slots are [0, 8, 16]; or admitted at 09:02
        # to an Enoxaparin SC daily order whose only slot is [8]),
        # every day-0 slot fails the ``scheduled < admission_time``
        # guard below and the order gets ZERO MA on day 0. A short LOS
        # then discharges the patient before day 1's first slot fires,
        # leaving a completed MedicationRequest with no
        # MedicationAdministration (3 such orphans in the JP p=10000
        # s500 sample). Add an ad-hoc first dose at
        # ``admission_time + jitter`` (same shape as the STAT first-dose
        # path above but for routine day-0 orders) so every placed
        # medication order gets at least one administration on day 0.
        # Guarded on ``stat_first_dose_time is None`` so STAT orders
        # keep their bundle-mandated 30-60min first dose window
        # unchanged.
        if day == 0 and admin_hours and stat_first_dose_time is None:
            day0_slots = [
                datetime(admission_time.year, admission_time.month, admission_time.day, h, 0) for h in admin_hours
            ]
            if all(s < admission_time for s in day0_slots):
                scheduled_times.append(
                    admission_time
                    + timedelta(
                        minutes=int(
                            rng.integers(MAR_STAT_FIRST_DOSE_DELAY_MIN, MAR_STAT_FIRST_DOSE_DELAY_MAX_EXCLUSIVE)
                        )
                    )
                )

        for hour in admin_hours:
            scheduled = datetime(admission_time.year, admission_time.month, admission_time.day, hour, 0) + timedelta(
                days=day
            )

            if scheduled < admission_time:
                continue
            # Skip the scheduled-grid slot if it is within 90min of the STAT
            # ad-hoc dose to avoid a double administration back-to-back.
            if (
                stat_first_dose_time is not None
                and abs((scheduled - stat_first_dose_time).total_seconds()) < MAR_STAT_DUPLICATE_AVOIDANCE_WINDOW_SEC
            ):
                continue
            scheduled_times.append(scheduled)

        for scheduled in scheduled_times:
            # Determine status
            status = "given"
            hold_reason = None

            # Hold conditions (clinical)
            if "antihypertensive" in drug_name.lower() and hasattr(patient, "baseline_vitals"):
                if patient.baseline_vitals.systolic_bp < MAR_ANTIHYPERTENSIVE_HOLD_SBP_THRESHOLD:
                    status, hold_reason = "held", f"SBP < {MAR_ANTIHYPERTENSIVE_HOLD_SBP_THRESHOLD}"

            # Patient refusal (~1.5%)
            if rng.random() < MAR_PATIENT_REFUSAL_PROBABILITY:
                status = "refused"

            # Jitter
            actual = (
                scheduled + timedelta(minutes=float(rng.normal(MAR_JITTER_MEAN_MIN, MAR_JITTER_STD_MIN)))
                if status == "given"
                else None
            )

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


# ---------------------------------------------------------------------------
# Issue #1066 (drug_safety): admission-order contraindication gate.
# ---------------------------------------------------------------------------


def apply_drug_safety_gate_to_admission_orders(
    admission_orders: list[Order],
    patient: PatientProfile,
    encounter_id: str,
    admission_time: datetime,
    attending_id: str,
    protocol: Any = None,
    country: str = "us",
) -> list[Order]:
    """Post-hoc filter admission_orders through drug_safety.check_pair.

    Real EHR CPOE prevents contraindicated orders at entry time; this
    function reproduces that by walking the emitted MedicationOrder list
    in order, checking each candidate against every previously-accepted
    med (home + acute), and:

      - severity == major / contraindicated: drop the candidate, try
        ``suggest_alternative`` (disease_ctx-first, generic pool second),
        emit the substitute in place if one is available.
      - severity == moderate: keep the order but append a MR.note-shaped
        caution dict to ``order.notes`` (order-level list; downstream FHIR
        MR builder consumes it in Task 11).
      - severity == minor / allowed: keep unchanged.

    Every skip (with or without substitute) is appended to
    ``patient.safety_skip_log`` with ``encounter_id`` set to the current
    admission and ``context_hint`` derived from the verdict's
    ``substitution_hint``.

    Non-medication orders (labs, imaging, supportive/care-plan) pass
    through unchanged.

    Never raises. Determinism: no RNG consumed — verdicts are pure yaml
    lookups; substitution picks the first conflict-free alternative in
    yaml order.
    """
    from clinosim.modules import drug_safety
    from clinosim.modules.drug_safety.verdict import SafetySkipEntry

    # Existing active meds visible to the gate: patient's home meds
    # (already-accepted, already in patient.current_medications) at the
    # start of the pass. The activator (Task 8) has ALREADY run the gate
    # against home_med derivation, so this list represents chronic pairs
    # that were approved (or that pre-date the gate — see the
    # already-chronic bypass below).
    home_med_names: list[str] = [m.drug_name for m in (patient.current_medications or []) if m.drug_name]
    # Canonicalise once so the bypass check below matches regardless of
    # dose-suffixed input.
    _canonical_home = {drug_safety.canonical_name(name) or name.strip().lower() for name in home_med_names}

    out: list[Order] = []
    accepted_med_names: list[str] = list(home_med_names)
    substitute_seq = 0

    for order in admission_orders:
        if order.order_type != OrderType.MEDICATION:
            out.append(order)
            continue

        candidate = order.display_name or ""
        if not candidate:
            out.append(order)
            continue

        # Issue #1066: home-medication continuation orders re-emit drugs already
        # in ``patient.current_medications``. The activator has already made
        # the chronic-pair decision (Task 8); re-gating a home-med continuation
        # against its own siblings would spuriously skip legitimate chronic
        # co-therapy (e.g. Apixaban continuation getting flagged against a
        # sibling Aspirin that itself sits in current_medications from a
        # separate chronic condition — see the anticoag-carryforward
        # integration test). Only gate NEW additions on top of the chronic
        # baseline.
        _canonical_candidate = drug_safety.canonical_name(candidate) or candidate.strip().lower()
        if _canonical_candidate in _canonical_home:
            out.append(order)
            accepted_med_names.append(candidate)
            continue

        verdicts = drug_safety.check_candidate_against_active(candidate, accepted_med_names)
        worst = max(
            (v for v in verdicts if not v.is_allowed),
            key=lambda v: drug_safety.SEVERITY_RANK[v.severity],
            default=None,
        )

        if worst is not None and worst.default_action == "skip":
            indication = worst.substitution_hint
            alt = drug_safety.suggest_alternative(
                candidate,
                indication,
                active_meds=accepted_med_names,
                disease_ctx=protocol,
                country=country,
            )
            patient.safety_skip_log.append(
                SafetySkipEntry(
                    encounter_id=encounter_id,
                    candidate_drug=candidate,
                    candidate_drug_ja=(drug_safety.japanese_display(candidate) or candidate),
                    active_conflict=worst.matched_active_drug or "",
                    active_conflict_ja=(
                        drug_safety.japanese_display(worst.matched_active_drug or "")
                        or (worst.matched_active_drug or "")
                    ),
                    verdict=worst,
                    substituted_with=alt.drug if alt else None,
                    substituted_with_ja=(alt.drug_ja if alt else None),
                    context_hint=indication,
                    timestamp=admission_time.isoformat(),
                )
            )
            if alt is None:
                # Fully skip — order dropped
                continue
            # Emit substitute in place
            substitute_seq += 1
            sub_order = Order(
                order_id=f"ORD-{encounter_id}-SUB-{substitute_seq:02d}",
                encounter_id=encounter_id,
                patient_id=patient.patient_id,
                order_type=OrderType.MEDICATION,
                order_code="",
                display_name=alt.drug,
                urgency=order.urgency or "routine",
                clinical_intent=f"Alternative for {candidate} (contraindication avoided): {alt.drug}",
                clinical_intent_ja=f"{candidate} の禁忌回避のため代替処方: {alt.drug_ja}",
                ordered_datetime=order.ordered_datetime,
                ordered_by=order.ordered_by or attending_id,
                status=OrderStatus.PLACED,
                route=alt.default_route,
                frequency=alt.default_frequency.upper() if alt.default_frequency else "",
            )
            if alt.default_dose:
                from clinosim.modules.order.engine import enrich_medication_order

                enrich_medication_order(sub_order, alt.default_dose)
            out.append(sub_order)
            accepted_med_names.append(alt.drug)
            continue

        if worst is not None and worst.default_action == "emit_with_note":
            locale = country.lower()
            note_text = worst.rationale_ja if locale == "jp" else worst.rationale_en
            prefix = "併用注意: " if locale == "jp" else "Drug interaction (caution): "
            note_entry = {
                "text": f"{prefix}{note_text}",
                "authorReference": {"display": "clinosim drug_safety v1"},
            }
            order.notes.append(note_entry)

        out.append(order)
        accepted_med_names.append(candidate)

    return out
