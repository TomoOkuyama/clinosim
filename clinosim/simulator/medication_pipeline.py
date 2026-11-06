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

import functools
from datetime import datetime, timedelta
from functools import cache
from pathlib import Path
from typing import Any

import numpy as np

from clinosim.codes.drugs import drug_classes, drug_key, drug_ref, get_drug, same_drug
from clinosim.countries import lang_for
from clinosim.datafiles import load_data_yaml
from clinosim.locale.i18n import t
from clinosim.locale.localized import localized, localized_field
from clinosim.modules.observation.order_routing import lab_order_targets
from clinosim.modules.physiology.renal_thresholds import (
    METFORMIN_ADMISSION_HOLD_THRESHOLD,
    METFORMIN_RENAL_RESERVE_THRESHOLD,
)
from clinosim.modules.staff.engine import FALLBACK_NURSE_ID, StaffRoster, assign_staff
from clinosim.simulator._mar_thresholds import (
    MAR_JITTER_MEAN_MIN,
    MAR_JITTER_STD_MIN,
    MAR_PATIENT_REFUSAL_PROBABILITY,
    MAR_STAT_DUPLICATE_AVOIDANCE_WINDOW_SEC,
    MAR_STAT_FIRST_DOSE_DELAY_MAX_EXCLUSIVE,
    MAR_STAT_FIRST_DOSE_DELAY_MIN,
)
from clinosim.simulator.helpers import _determine_route
from clinosim.types.clinical import PhysiologicalState
from clinosim.types.encounter import (
    MedicationAdministration,
    Order,
    OrderStatus,
    OrderType,
    VitalSignRecord,
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


_VITAL_HOLD_LABELS: dict[str, str] = {"systolic_bp": "SBP", "heart_rate": "HR"}


@functools.cache
def _hold_conditions() -> tuple[dict, ...]:
    from clinosim.locale.loader import load_chronic_medications

    rules: list[dict] = []
    for block in load_chronic_medications().values():
        if isinstance(block, dict):
            rules.extend(r for r in block.get("hold_conditions") or [] if isinstance(r, dict))
    return tuple(rules)


def metformin_admission_hold_threshold() -> float:
    """Renal-function threshold for holding metformin on admission, from the
    Metformin ``hold_conditions`` entry of ``chronic_medications.yaml``
    (Issue #2296); the code constant is the fallback."""
    for rule in _hold_conditions():
        if str(rule.get("drug", "")).lower() == "metformin" and rule.get("field") == "renal_function":
            return float(rule["threshold"])
    return METFORMIN_ADMISSION_HOLD_THRESHOLD


@functools.cache
def renal_medication_rules() -> dict[str, str]:
    """Drug key (catalog drug_id, ``codes.drugs.drug_key``) -> admission action
    ("hold" / "reduce") for renal impairment, from
    ``renal_medication_rules.yaml`` (Issue #2296; keyed by identity, #2377)."""
    from clinosim.codes.drugs import drug_key
    from clinosim.datafiles import load_data_yaml

    data = load_data_yaml(Path(__file__).resolve().parent / "reference_data" / "renal_medication_rules.yaml")
    return {drug_key(str(k)): str(v) for k, v in (data.get("renal_drugs") or {}).items()}


def mar_vital_hold_reason(drug_name: str, vitals: Any) -> str | None:
    """Hold reason ("SBP < 90") when a vital-sign hold parameter in
    ``chronic_medications.yaml`` applies to ``drug_name``, else None."""
    if vitals is None or not drug_name:
        return None
    for rule in _hold_conditions():
        field = rule.get("field")
        if field not in _VITAL_HOLD_LABELS or rule.get("direction") != "below":
            continue
        if not same_drug(str(rule.get("drug", "")), drug_name):
            continue
        value = getattr(vitals, field, None)
        threshold = rule.get("threshold")
        if value is not None and threshold is not None and value < threshold:
            return f"{_VITAL_HOLD_LABELS[field]} < {threshold}"
    return None


def _log_disease_medication_hold(
    patient: PatientProfile,
    encounter_id: str,
    held_drug_name: str,
    held_drug_name_ja: str,
    hold_reason: str,
    disease_id: str,
    timestamp: datetime,
) -> None:
    """Issue #1403: record a disease-protocol ``medication_holds`` silent
    drop on ``patient.safety_skip_log`` so the narrative
    ``considered_but_not_prescribed`` context surface can render the
    clinical reasoning (e.g. "Enalapril was held during this admission
    because of AKI protocol; resume after renal function recovers").

    Pre-fix the hold was invisible: the MAR simply lacked the drug,
    and the LLM had no way to know a home med was intentionally paused
    (risk: LLM fabricates "continued on Enalapril" from PMH inference).
    """
    from clinosim.modules.drug_safety.verdict import (
        SafetySkipEntry,
        SafetyVerdict,
    )

    verdict = SafetyVerdict(
        severity="major",
        rule_id=f"medication-hold:{disease_id or 'protocol'}",
        matched_classes=None,
        matched_active_drug=hold_reason,
        rationale_en=t("order_intent.protocol_hold", "en", reason=hold_reason),
        rationale_ja=t("order_intent.protocol_hold", "ja", reason=hold_reason),
        substitution_hint=None,
    )
    # active_conflict phrasing carries the CLINICAL REASON (English +
    # Japanese) — the narrative Rule 2 hold cadence reads this as the
    # "because of ~" clause. Encoding the reason on the conflict field
    # (instead of a separate `reason_ja` field) reuses the existing
    # narrative context payload shape without a schema change.
    reason_en = _hold_reason_english(hold_reason)
    reason_ja = _hold_reason_japanese(hold_reason)
    patient.safety_skip_log.append(
        SafetySkipEntry(
            encounter_id=encounter_id,
            candidate_drug=held_drug_name,
            candidate_drug_ja=held_drug_name_ja,
            active_conflict=reason_en,
            active_conflict_ja=reason_ja,
            verdict=verdict,
            substituted_with=None,
            substituted_with_ja=None,
            context_hint=hold_reason,
            timestamp=timestamp.isoformat(),
            event_type="hold",
        )
    )


# Small locale-aware translator for the free-form YAML `reason` strings
# used in disease-protocol `medication_holds`. Only a handful of unique
# reasons are used in production YAML today; the fallback returns the
# raw string so a new reason lands correctly (English side) with an
# imperfect JA rendering until translated. Kept in the pipeline module
# (rather than a shared table) so it stays scoped to the hold semantic.
@cache
def _hold_reasons() -> dict[str, dict[str, str]]:
    """Hold-reason displays (``locale/shared/medication_hold_reasons.yaml``,
    Issue #2405), keyed by the reason text authored in disease YAMLs."""
    path = Path(__file__).resolve().parents[1] / "locale" / "shared" / "medication_hold_reasons.yaml"
    data = load_data_yaml(path) or {}
    return {str(k): dict(v) for k, v in (data.get("reasons") or {}).items()}


def _hold_reason_english(reason: str) -> str:
    return localized(_hold_reasons().get(reason), "en", fallback=reason)


def _hold_reason_japanese(reason: str) -> str:
    return localized(_hold_reasons().get(reason), "ja", fallback=reason)


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
    has_renal_impairment = has_ckd or initial_renal < metformin_admission_hold_threshold()

    # Held drug set from disease protocol's medication_holds (YAML-driven,
    # protocol side — unchanged semantics, now applied against current_meds).
    held_drugs: set[str] = set()
    hold_reasons: dict[str, str] = {}
    if protocol and hasattr(protocol, "medication_holds"):
        for hold in protocol.medication_holds or []:
            reason = hold.get("reason", "disease-specific hold")
            for drug in hold.get("drugs", []):
                held_drugs.add(drug_key(drug))
                hold_reasons[drug_key(drug)] = reason

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
        med_key = med.drug_id or drug_key(drug_name)
        intent_drug = f"{drug_name} {med.dose}".strip() if med.dose else drug_name
        intent = t("order_intent.home_med_continue", "en", drug=intent_drug)
        # Issue #871: parallel JA display for JP SR reasonCode.text. `intent_drug`
        # includes the raw drug name + dose (which may be EN or JA depending on
        # the source); the shell is translated.
        intent_ja = t("order_intent.home_med_continue", "ja", drug=intent_drug)

        # 1. Protocol-driven disease-specific holds.
        yaml_held = False
        matched_hold_name = med_key if med_key in held_drugs else ""
        if matched_hold_name:
            yaml_held = True
        if yaml_held:
            # Issue #1403: log the silent hold so the narrative
            # `considered_but_not_prescribed` context surface can
            # render "Enalapril was held during this admission because
            # of AKI protocol" instead of leaving the home med
            # invisible to the LLM's home-medication reconciliation.
            _log_disease_medication_hold(
                patient,
                encounter_id=encounter_id,
                held_drug_name=drug_name,
                held_drug_name_ja=getattr(med, "drug_name_ja", "") or drug_name,
                hold_reason=hold_reasons.get(matched_hold_name, "disease-specific hold"),
                disease_id=disease_id,
                timestamp=admission_time,
            )
            continue  # silently skip — not ordered (but now logged)

        # 2. Metformin: renal-function-based hold.
        if med_key == "metformin" and (initial_renal < metformin_admission_hold_threshold() or has_renal_impairment):
            continue

        # 3. Renal dose adjustment for CKD patients.
        # Issue #2296: one renal drug list shared with discharge.
        if has_renal_impairment and renal_reserve < METFORMIN_RENAL_RESERVE_THRESHOLD:
            action = renal_medication_rules().get(med_key)
            if action == "hold":
                continue  # held
            if action == "reduce":
                intent += t("order_intent.dose_reduced_renal", "en")
                # Issue #871: mirror the annotation on the JA display.
                intent_ja += t("order_intent.dose_reduced_renal", "ja")

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
        # A vital sign (SpO2) is recorded with the vitals, not ordered (Issue #2583).
        if not lab_order_targets(mon["test"]):
            continue
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
                        clinical_intent=mon.get("intent")
                        or t("order_intent.chronic_monitoring", "en", test=mon["test"]),
                        # Issue #871: JA display for JP SR reasonCode.text.
                        # Reads `intent_ja` from the YAML spec; falls back to
                        # a shell-translated default when the YAML has not
                        # yet been extended.
                        clinical_intent_ja=mon.get("intent_ja")
                        or t("order_intent.chronic_monitoring", "ja", test=mon["test"]),
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
                        clinical_intent=mon.get("intent")
                        or t("order_intent.chronic_monitoring", "en", test=mon["test"]),
                        # Issue #871: JA display for JP SR reasonCode.text.
                        # Reads `intent_ja` from the YAML spec; falls back to
                        # a shell-translated default when the YAML has not
                        # yet been extended.
                        clinical_intent_ja=mon.get("intent_ja")
                        or t("order_intent.chronic_monitoring", "ja", test=mon["test"]),
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
                clinical_intent=mon.get("intent") or t("order_intent.chronic_monitoring", "en", test=mon["test"]),
                # Issue #871: JA display for JP SR reasonCode.text.
                clinical_intent_ja=mon.get("intent_ja") or t("order_intent.chronic_monitoring", "ja", test=mon["test"]),
                ordered_datetime=order_time,
                ordered_by=ordered_by,
                status=OrderStatus.PLACED,
            )
        )

    return orders


PRN_PAIN_NON_OPIOID_MIN: int = 4
PRN_PAIN_OPIOID_MIN: int = 7
PRN_SYMPATHETIC_MIN: float = 0.25
PRN_ADMIN_DELAY_MIN: int = 10


def prn_category(drug_name: str) -> str | None:
    """Trigger class of a PRN drug (Issue #2085): non_opioid / opioid analgesics
    follow the pain score, benzodiazepines follow autonomic symptoms (CIWA)."""
    # Catalog classes (Issue #2372): an opioid combination such as
    # acetaminophen / codeine counts as an opioid.
    classes = set(drug_classes(drug_name or ""))
    if "opioid" in classes or "analgesic.opioid" in classes:
        return "opioid"
    if "analgesic.non_opioid" in classes or ("nsaid" in classes and "antiplatelet" not in classes):
        return "non_opioid"
    if "benzodiazepine" in classes:
        return "benzodiazepine"
    return None


def _is_triggered_prn(order: Order) -> bool:
    return "PRN" in str(getattr(order, "frequency", "") or "").upper() and prn_category(order.display_name) is not None


def generate_prn_administrations(
    orders: list[Order],
    vitals_today: list[VitalSignRecord],
    state: PhysiologicalState,
    last_given: dict[str, datetime],
) -> list[MedicationAdministration]:
    """On-demand doses of PRN analgesics / benzodiazepines (Issue #2085).

    At each vitals round: non-opioids when pain >= 4, opioids when pain >= 7,
    benzodiazepines while ``sympathetic_activation`` >= 0.25 (CIWA-Ar >= 8-10).
    The order's frequency is the minimum interval; ``last_given`` (order_id ->
    last dose time) carries it across days. Deterministic (no RNG draw).
    """
    out: list[MedicationAdministration] = []
    prn_orders = [
        o
        for o in orders
        if o.order_type == OrderType.MEDICATION and o.status == OrderStatus.PLACED and _is_triggered_prn(o)
    ]
    if not prn_orders:
        return out
    for vs in sorted(vitals_today, key=lambda v: v.timestamp):
        pain = vs.pain_score
        for order in prn_orders:
            cat = prn_category(order.display_name)
            if cat == "non_opioid":
                due = pain is not None and pain >= PRN_PAIN_NON_OPIOID_MIN
            elif cat == "opioid":
                due = pain is not None and pain >= PRN_PAIN_OPIOID_MIN
            else:
                due = state.sympathetic_activation >= PRN_SYMPATHETIC_MIN
            if not due:
                continue
            per_day = int(getattr(order, "frequency_per_day", None) or 4)
            interval = timedelta(hours=24 / max(per_day, 1))
            prev = last_given.get(order.order_id)
            given_at = vs.timestamp + timedelta(minutes=PRN_ADMIN_DELAY_MIN)
            if prev is not None and given_at - prev < interval:
                continue
            last_given[order.order_id] = given_at
            dose = f"{order.dose_quantity}{order.dose_unit}" if order.dose_quantity is not None else ""
            out.append(
                MedicationAdministration(
                    order_id=order.order_id,
                    drug_name=order.display_name,
                    scheduled_datetime=given_at,
                    actual_datetime=given_at,
                    status="given",
                    dose=f"{dose} PRN".strip(),
                    route=order.route or "",
                    administered_by=vs.measured_by or "",
                )
            )
    return out


def _given_dose_text(order: Order, patient: PatientProfile) -> str:
    """The dose an administration records: the order's dose, or for a per-kg /
    per-m² order the absolute amount given (Issue #2750)."""
    from clinosim.modules.order.absolute_dose import absolute_dose, is_continuous_infusion

    if is_continuous_infusion(order.frequency or "", order.display_name or ""):
        return f"{order.dose_quantity}{order.dose_unit}"
    given = absolute_dose(
        order.dose_quantity,
        order.dose_unit,
        float(getattr(patient, "height_cm", 0.0) or 0.0),
        float(getattr(patient, "weight_kg", 0.0) or 0.0),
    )
    if given is not None:
        return f"{given[0]:g}{given[1]}"
    return f"{order.dose_quantity}{order.dose_unit}"


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
        if _is_triggered_prn(order):
            continue  # given on demand by generate_prn_administrations (Issue #2085)
        # Determine administration times based on drug and route
        route = order.route or _determine_route(drug_name, order.clinical_intent, order.drug_id)

        # Issue #913: MAR admin count must match
        # ``MedicationRequest.dosageInstruction.timing.repeat.frequency``
        # (both derived from the same order — before this fix, MAR ran
        # on a hardcoded drug-name heuristic that diverged from what the
        # prescription said → 60 % of pairs over-admin, ~3× on-chart
        # over-dose signature).
        #
        # Ordering:
        # 1. Antibiotic clinical-override (Q6H / Q8H) — the catalog's
        #    ``scheduled_interval_hours`` for β-lactam combos and
        #    carbapenems, whose 1/day default (from the enricher) would be
        #    clinically dangerous (Issue #2389). Ceftriaxone (correctly
        #    1/day) has none.
        # 2. Explicit prescribed frequency (``order.frequency_per_day``) —
        #    honours the parsed prescription frequency, aligning MAR to MR.
        # 3. Drug / route defaults — the enricher's DAILY default fires
        #    for parseable-dose but no-frequency orders, so this branch is
        #    rarely hit today; kept for orders without a resolvable
        #    frequency at all (the catalog's ``default_interval_hours``).
        drug_upper = drug_name.upper()
        _drug = get_drug(order.drug_id or drug_ref(drug_name))
        _scheduled_h = _drug.scheduled_interval_hours if _drug is not None else None
        _freq_per_day = getattr(order, "frequency_per_day", None)
        if _scheduled_h:
            admin_hours = list(range(0, 24, _scheduled_h))  # q6h / q8h clinical override
        elif _freq_per_day and _freq_per_day > 0:
            admin_hours = _admin_hours_from_frequency(int(_freq_per_day))
        else:
            # Fallback (unresolvable frequency).
            if (_drug is not None and _drug.default_interval_hours == 24) or route == "SC":
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
        # Issue #2611: a one-time dose is given once, shortly after it is
        # ordered (or after admission), on the day it is ordered only.
        if getattr(order, "single_dose", False):
            ordered = getattr(order, "ordered_datetime", None) or admission_time
            if (ordered.date() - admission_time.date()).days != day:
                continue
            given = max(ordered, admission_time) + timedelta(
                minutes=int(rng.integers(MAR_STAT_FIRST_DOSE_DELAY_MIN, MAR_STAT_FIRST_DOSE_DELAY_MAX_EXCLUSIVE))
            )
            mars.append(
                MedicationAdministration(
                    order_id=order.order_id,
                    drug_name=drug_name,
                    scheduled_datetime=given,
                    actual_datetime=given,
                    status="given",
                    dose=_given_dose_text(order, patient) if order.dose_quantity else order.display_name,
                    route=route,
                    administered_by=nurse_id,
                )
            )
            continue

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
            # Issue #2296: hold parameters from chronic_medications.yaml
            # hold_conditions (the former "antihypertensive" name test matched
            # no drug and never fired).
            vital_hold = mar_vital_hold_reason(drug_name, getattr(patient, "baseline_vitals", None))
            if vital_hold:
                status, hold_reason = "held", vital_hold

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
                dose_text = _given_dose_text(order, patient)
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
                    route=order.route or _determine_route(drug_name, order.clinical_intent, order.drug_id),
                    administered_by=nurse_id,
                    hold_reason=hold_reason,
                )
            )

    return mars


# ---------------------------------------------------------------------------
# Issue #1066 (drug_safety): admission-order contraindication gate.
# ---------------------------------------------------------------------------


def apply_drug_safety_gate_to_orders(
    candidate_orders: list[Order],
    *,
    patient: PatientProfile,
    encounter_id: str,
    ordered_datetime: datetime,
    attending_id: str = "",
    protocol: Any = None,
    country: str = "us",
    already_accepted_meds: list[str] | None = None,
) -> list[Order]:
    """Filter a stream of candidate medication Orders through
    ``drug_safety.check_pair``.

    C7b / Issue #1100 generalization: this is the shared per-order gate
    used by every issuance path (admission, daily_loop step-up,
    outpatient, ED, POST_ENCOUNTER enrichers). Real EHR CPOE prevents
    contraindicated orders at entry time; this function reproduces that
    by walking the candidate MedicationOrder list in order, checking
    each candidate against every previously-accepted med, and:

      - severity == major / contraindicated: drop the candidate, try
        ``suggest_alternative`` (disease_ctx-first, generic pool second),
        emit the substitute in place if one is available.
      - severity == moderate: keep the order but append a MR.note-shaped
        caution dict to ``order.notes`` (order-level list; downstream
        FHIR MR builder consumes it).
      - severity == minor / allowed: keep unchanged.

    ``already_accepted_meds`` seeds the accepted-med set. When ``None``
    (default) it is initialized from ``patient.current_medications`` —
    matching the admission-orders behavior. Callers coming from
    post-admission paths (daily_loop, POST_ENCOUNTER enrichers) should
    pass in the union of home meds + admission-accepted meds + any
    already-processed candidates for the current pass.

    Every skip (with or without substitute) is appended to
    ``patient.safety_skip_log`` with ``encounter_id`` set and
    ``context_hint`` derived from the verdict's ``substitution_hint``.

    Non-medication orders (labs, imaging, supportive/care-plan) pass
    through unchanged.

    Never raises. Determinism: no RNG consumed — verdicts are pure yaml
    lookups; substitution picks the first conflict-free alternative in
    yaml order.
    """
    from clinosim.modules import drug_safety
    from clinosim.modules.drug_safety.verdict import SafetySkipEntry

    # Existing active meds visible to the gate. When ``already_accepted_meds``
    # is None, seed from patient home meds (matches admission-orders
    # historical behavior). Otherwise use the caller-supplied set — it
    # already reflects home + admission + prior-day acceptance for
    # post-admission passes.
    home_med_names: list[str] = [m.drug_name for m in (patient.current_medications or []) if m.drug_name]
    if already_accepted_meds is None:
        seed = list(home_med_names)
    else:
        seed = list(already_accepted_meds)
    # Canonicalise once so the bypass check below matches regardless of
    # dose-suffixed input. Bypass covers home meds specifically so a
    # continue-home-med order doesn't get flagged against its own
    # chronic-list sibling.
    _canonical_home = {drug_safety.canonical_name(name) or name.strip().lower() for name in home_med_names}

    out: list[Order] = []
    accepted_med_names: list[str] = seed
    substitute_seq = 0

    for order in candidate_orders:
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
                    timestamp=ordered_datetime.isoformat(),
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
                clinical_intent=t(
                    "order_intent.contraindication_alternative", "en", candidate=candidate, drug=alt.drug
                ),
                clinical_intent_ja=t(
                    "order_intent.contraindication_alternative", "ja", candidate=candidate, drug=alt.drug_ja
                ),
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
            note_text = localized_field(worst, "rationale", lang_for(locale))
            note_entry = {
                "text": t("order_intent.interaction_caution", lang_for(locale), note=note_text),
                "authorReference": {"display": "clinosim drug_safety v1"},
            }
            order.notes.append(note_entry)

        out.append(order)
        accepted_med_names.append(candidate)

    return out


def apply_drug_safety_gate_to_admission_orders(
    admission_orders: list[Order],
    patient: PatientProfile,
    encounter_id: str,
    admission_time: datetime,
    attending_id: str,
    protocol: Any = None,
    country: str = "us",
) -> list[Order]:
    """Backward-compat wrapper preserved from before C7b (#1100).

    Delegates to :func:`apply_drug_safety_gate_to_orders` with
    ``already_accepted_meds=None`` so the general helper seeds from
    ``patient.current_medications`` (home meds) — matching the
    admission-orders historical behavior.

    New call sites should use :func:`apply_drug_safety_gate_to_orders`
    directly and pass an explicit ``already_accepted_meds`` list that
    reflects home + admission + prior-day accepted meds.
    """
    return apply_drug_safety_gate_to_orders(
        admission_orders,
        patient=patient,
        encounter_id=encounter_id,
        ordered_datetime=admission_time,
        attending_id=attending_id,
        protocol=protocol,
        country=country,
        already_accepted_meds=None,
    )
