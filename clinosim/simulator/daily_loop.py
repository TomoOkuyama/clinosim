"""Per-day state machine extracted from `inpatient.py` (Issue #552 residual).

Contains the per-day loop that drives state update, orders, labs, MAR,
vitals, ADL/IO, complications, and discharge check for each simulated
day of an inpatient encounter. Extracted to reduce `inpatient.py`'s file
size ('s sibling-file convention: `lab_pipeline.py`,
`vitals_pipeline.py`, etc.).

Function bodies moved verbatim; byte-diff-neutral vs pre-extraction.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta
from typing import Any

import numpy as np

from clinosim.modules._shared import MED_STOP_ORDER_ID_MARKER, sanitize_id_token
from clinosim.modules.clinical_course._complication_risk_conditions import DRUG_CLASSES, ComplicationContext
from clinosim.modules.clinical_course.engine import (
    apply_diagnosis_modifier,
    compute_diagnosis_effectiveness,
    evaluate_complications,
    get_daily_directive,
    natural_recovery_directive,
)
from clinosim.modules.diagnosis.engine import update_differential
from clinosim.modules.disease.protocol import DiseaseProtocol
from clinosim.modules.observation.engine import lab_panel_components, medications_in_effect
from clinosim.modules.order.engine import place_daily_lab_orders, place_imaging_orders
from clinosim.modules.order.treatment_classifier import (
    classify_encounter_treatment,
    classify_escalation_treatment,
)
from clinosim.modules.physiology.engine import (
    apply_state_delta,
    derive_lab_values,
    medication_flags_from_context,
    scenario_flags_from_protocol,
    update,
)
from clinosim.modules.procedure.engine import build_intubation_procedure
from clinosim.modules.staff.engine import (
    FALLBACK_NURSE_ID,
    StaffRoster,
    assign_staff,
)
from clinosim.simulator._daily_loop_thresholds import (
    AIRWAY_CONSCIOUSNESS_MIN,
    AIRWAY_ESCALATION_HOUR,
    AIRWAY_OXYGENATION_MIN,
    ARCHETYPE_DAY_SHIFT_PROBABILITY,
    DIET_CLEAR_LIQUID_INFLAMMATION_THRESHOLD,
    DIET_SOFT_INFLAMMATION_THRESHOLD,
    ICU_DISTRIBUTIVE_SHOCK_INFLAMMATION,
    ICU_DISTRIBUTIVE_SHOCK_PERFUSION_MAX,
    ICU_HIGH_FLOW_OXYGENATION,
    ICU_SHOCK_PERFUSION_MAX,
    LAB_EARLY_MORNING_HOUR,
    LAB_EARLY_MORNING_MIN_END_EXCLUSIVE,
    LAB_EARLY_MORNING_MIN_START,
    LAB_EARLY_MORNING_PROBABILITY,
    LAB_FREQ_MULT_LATE_STAY_STABLE,
    LAB_FREQ_MULT_NEAR_DISCHARGE,
    LAB_FREQ_MULT_SEVERITY_FALLBACK,
    LAB_FREQ_MULT_SEVERITY_MILD,
    LAB_FREQ_MULT_SEVERITY_MODERATE,
    LAB_FREQ_MULT_SEVERITY_SEVERE,
    LAB_FREQ_MULT_WEEKEND,
    LAB_LATE_STAY_INFLAMMATION_MAX,
    LAB_LATE_STAY_MIN_DAY,
    LAB_MIN_END_EXCLUSIVE,
    LAB_MIN_START,
    LAB_MORNING_HOUR,
    LAB_NEAR_DISCHARGE_DAY_OFFSET,
    LAB_NEAR_DISCHARGE_INFLAMMATION_MAX,
    TREATMENT_ESCALATION_DAY,
    TREATMENT_ESCALATION_INFLAMMATION_MIN,
)
from clinosim.simulator.complications import build_complication
from clinosim.simulator.discharge_gate import (
    expected_state_multiplier,
    extend_stay_for_symptoms,
    mortality_state_multiplier,
)
from clinosim.simulator.helpers import _check_discharge_ready, _evaluate_mortality
from clinosim.simulator.lab_pipeline import _run_lab_result_pipeline
from clinosim.simulator.medication_pipeline import (
    _generate_mar,
    _place_chronic_monitoring_orders,
    generate_prn_administrations,
)
from clinosim.simulator.vitals_pipeline import (
    _generate_adl_assessment,
    _generate_daily_io,
    _generate_vitals,
)
from clinosim.types.clinical import PhysiologicalState
from clinosim.types.config import HealthcareSystemConfig
from clinosim.types.encounter import (
    MedicationAdministration,
    Order,
    OrderResult,
    OrderStatus,
    OrderType,
    VitalSignRecord,
)
from clinosim.types.patient import PatientProfile


def _planned_dvt_prophylaxis(patient: Any, protocol: Any, admission_time: datetime, target_los: int) -> bool:
    """Whether the prophylaxis module will order pharmacologic VTE prophylaxis
    for this stay (its order is added after the loop): same skip rules,
    evaluated with the planned LOS and the protocol's primary diagnosis."""
    from types import SimpleNamespace

    from clinosim.modules.prophylaxis.engine import should_skip_dvt_prophylaxis

    encounter = SimpleNamespace(
        admission_datetime=admission_time, discharge_datetime=admission_time + timedelta(days=max(target_los, 1))
    )
    primary = str(((getattr(protocol, "icd_codes", None) or {}).get("primary")) or "")
    skip, _reason = should_skip_dvt_prophylaxis(patient=patient, encounter=encounter, admission_dx_code=primary)
    return not skip


def _complication_context(
    patient: Any,
    orders: list,
    admission_time: datetime,
    *,
    icu_day: int | None,
    intubated_day: int | None,
    surgery_day: int | None,
    procedures: list,
    dvt_prophylaxis: bool | None = None,
) -> ComplicationContext:
    """Stay context for context-dependent complication risk factors (Issue #2101)."""
    meds = [o for o in orders if o.order_type == OrderType.MEDICATION and o.status == OrderStatus.PLACED]
    antibiotic_days = [
        (o.ordered_datetime.date() - admission_time.date()).days
        for o in meds
        if any(sub in (o.display_name or "").upper() for sub in DRUG_CLASSES["antibiotic"])
    ]
    return ComplicationContext(
        icu_day=icu_day,
        intubated_day=intubated_day,
        surgery_day=surgery_day,
        antibiotic_start_day=min(antibiotic_days) if antibiotic_days else None,
        medications={(o.display_name or "").upper() for o in meds},
        home_medications={(m.drug_name or "").upper() for m in getattr(patient, "current_medications", []) or []},
        procedure_types={getattr(p, "procedure_type", "") for p in procedures},
        dvt_prophylaxis=dvt_prophylaxis,
    )


def airway_escalation_needed(state: PhysiologicalState) -> bool:
    """GCS <= 8 range or refractory hypoxemia: secure the airway (Issue #2091)."""
    return (
        state.consciousness_impairment >= AIRWAY_CONSCIOUSNESS_MIN
        or state.oxygenation_impairment >= AIRWAY_OXYGENATION_MIN
    )


def icu_escalation_needed(state: PhysiologicalState) -> bool:
    """Airway escalation, shock-level perfusion, distributive shock or a
    high-flow oxygen requirement: ICU care (Issues #2091, #2110)."""
    return (
        airway_escalation_needed(state)
        or state.perfusion_status < ICU_SHOCK_PERFUSION_MAX
        or (
            state.inflammation_level >= ICU_DISTRIBUTIVE_SHOCK_INFLAMMATION
            and state.perfusion_status < ICU_DISTRIBUTIVE_SHOCK_PERFUSION_MAX
        )
        or state.oxygenation_impairment >= ICU_HIGH_FLOW_OXYGENATION
    )


SYMPTOM_AXES: tuple[str, ...] = (
    "sympathetic_activation",
    "pain_level",
    "oxygenation_impairment",
    "consciousness_impairment",
)


def apply_postoperative_pain(state: PhysiologicalState, day: int, surgery: tuple[int, float] | None) -> None:
    """Raise pain to the procedure's post-operative level on the operative day
    (Issue #2080); daily recovery lowers it afterwards."""
    if surgery is not None and day == surgery[0] and state.pain_level < surgery[1]:
        state.pain_level = surgery[1]


def apply_symptom_floor(state: PhysiologicalState, floor: dict[str, float]) -> None:
    """Keep symptom axes at or above the patient's chronic baseline.

    Daily recovery lowers the symptom axes toward 0; a patient with chronic
    hypoxemia or joint pain returns to that baseline, not to 0 (Issue #2061).
    """
    for axis, value in floor.items():
        if getattr(state, axis) < value:
            setattr(state, axis, value)


def _run_daily_loop(
    state: PhysiologicalState,
    patient: PatientProfile,
    disease_id: str,
    protocol: DiseaseProtocol,
    archetype: str,
    differential: Any,
    admission_orders: list[Order],
    admission_time: datetime,
    target_los: int,
    has_diabetes: bool,
    has_dyslipidemia: bool,  # Issue #1073 B8: E78 chronic condition → lipid modulation
    healthcare: HealthcareSystemConfig,
    roster: StaffRoster,
    rng: np.random.Generator,
    chronic_monitoring: list[dict] | None = None,
    country_key: str = "us",
    min_los: int = 3,
    hospital_state: Any = None,
    hospital_ops: dict | None = None,
    attending_id: str = "",
    department: str = "internal_medicine",
    severity: str = "moderate",
    encounter_id: str = "",
    imaging_seq_counter: dict[str, int] | None = None,
    symptom_floor: dict[str, float] | None = None,
    max_los: int | None = None,
    surgery: tuple[int, float] | None = None,
    prior_procedures: list | None = None,
) -> dict:
    """Run the day-by-day simulation loop. Returns all generated data."""

    all_orders = list(admission_orders)
    # Thread imaging sequence counter from caller (initialized at day=0 in
    # simulate_inpatient_encounter). Fallback to {"I": 0} for callers that
    # don't pass it (backward-compat for direct test calls of _run_daily_loop).
    _img_seq: dict[str, int] = imaging_seq_counter if imaging_seq_counter is not None else {"I": 0}
    all_lab_results: list[OrderResult] = []
    all_vitals: list[VitalSignRecord] = []
    all_mars: list[MedicationAdministration] = []
    prn_last_given: dict[str, datetime] = {}  # Issue #2085: PRN order -> last dose time
    all_io: list = []
    all_adl: list = []
    state_history = [deepcopy(state)]
    expected_mortality_multiplier = expected_state_multiplier(protocol)
    active_complications: set[str] = set()
    # Phase 1a schema: entries are dicts with onset_day / onset_datetime /
    # source (see clinosim.simulator.complications for the canonical shape).
    complications_occurred: list[dict[str, Any]] = []
    death_occurred = False
    icu_transferred = False
    icu_transferred_day_local: int = -1  # C5-22: day of ICU transfer
    intubated = False
    intubated_day: int | None = None  # Issue #2101: complication context
    dvt_prophylaxis_planned = _planned_dvt_prophylaxis(patient, protocol, admission_time, target_los)
    escalation_procedures: list = []  # Issue #2091: state-driven intubation records
    # Presentation already beyond the airway / ICU thresholds (e.g. GCS <= 8 on
    # arrival): intubate and transfer on the admission day.
    if airway_escalation_needed(state):
        intubated = True
        intubated_day = 0
        escalation_procedures.append(
            build_intubation_procedure(
                patient.patient_id,
                encounter_id,
                admission_time + timedelta(hours=1),
                "JP" if country_key == "japan" else "US",
                f"PROC-{patient.patient_id}-AIR00",
            )
        )
    if icu_escalation_needed(state):
        icu_transferred = True
        icu_transferred_day_local = 0

    prev_diet = ""  # last diet ordered for this patient; threaded through the day loop
    # The sampled target LOS is the stay ceiling; it is extended one day at a
    # time (up to max_los) while autonomic symptoms are uncontrolled. Stays
    # that never extend run exactly ``target_los`` days as before.
    los_ceiling = target_los
    for day in range(max(target_los, max_los or 0)):
        # State update with diagnosis-treatment feedback
        directive = get_daily_directive(
            archetype,
            day,
            patient.physiological_profile,
            protocol_archetypes=protocol.course_archetypes or None,
            age=patient.age,
            rng=rng,
        )

        # Phase 1: Dampen recovery if diagnosis is wrong
        dx_confidence = 0.0
        working_dx = None
        if differential.top_candidate:
            dx_confidence = differential.top_candidate.probability
            working_dx = differential.top_candidate.disease_code
        dx_difficulty = (protocol.diagnostic or {}).get("diagnostic_difficulty", 0.3)
        effectiveness = compute_diagnosis_effectiveness(
            working_dx,
            disease_id,
            dx_confidence,
            day,
            diagnostic_difficulty=dx_difficulty,
        )
        directive = apply_diagnosis_modifier(
            directive,
            effectiveness,
            current_volume=state.volume_status,
            current_ph=state.ph_status,
        )

        # Phase 2: Natural recovery (small baseline healing)
        nat_directive = natural_recovery_directive(
            day,
            disease_id,
            severity,
            patient.physiological_profile,
            treatment_effectiveness=effectiveness,
        )
        for var, delta in nat_directive.changes.items():
            directive.changes[var] = directive.changes.get(var, 0.0) + delta

        # Issue #1988: for DKA, snapshot the pre-day-0 physiological state
        # so that the admission ABG / BMP orders resolve against the
        # acute-presentation ph_status (-0.35 moderate / -0.60 severe)
        # rather than the end-of-day-0 state, which has already recovered
        # ~0.1 ph_status units toward normal and pushes the admission HCO3
        # above the ADA severity threshold (< 18 mEq/L defines DKA on
        # presentation; eval axis clinical.condition_lab_coherence.dka_hco3
        # measured 15 % of DKA encounters violating this before the fix).
        # Scoped to DKA — non-DKA cohorts stay byte-identical because the
        # per-order sub-RNG pipeline (see lab_pipeline.py) does not consume
        # master RNG, so swapping the lab-derivation state only shifts the
        # computed value and nothing else.
        _lab_state_pre_update = deepcopy(state) if (day == 0 and disease_id == "diabetic_ketoacidosis") else None
        state = update(state, directive, timedelta(days=1))
        if symptom_floor:
            apply_symptom_floor(state, symptom_floor)
        apply_postoperative_pain(state, day, surgery)
        state_history.append(deepcopy(state))

        # Daily lab orders (from Day 1) with context-dependent frequency
        if day >= 1:
            # Morning lab draw: 05:30-07:00 with jitter
            lab_hour = LAB_MORNING_HOUR
            lab_min = int(rng.integers(LAB_MIN_START, LAB_MIN_END_EXCLUSIVE))
            if rng.random() < LAB_EARLY_MORNING_PROBABILITY:
                lab_hour = LAB_EARLY_MORNING_HOUR
                lab_min = int(rng.integers(LAB_EARLY_MORNING_MIN_START, LAB_EARLY_MORNING_MIN_END_EXCLUSIVE))
            lab_time = datetime(
                admission_time.year,
                admission_time.month,
                admission_time.day,
                lab_hour,
                lab_min,
            ) + timedelta(days=day)

            # Context-dependent lab frequency modulation
            freq_mod = healthcare.lab_frequency_multiplier
            # Severity: severe patients get more frequent labs, mild get fewer
            severity_mult = {
                "severe": LAB_FREQ_MULT_SEVERITY_SEVERE,
                "moderate": LAB_FREQ_MULT_SEVERITY_MODERATE,
                "mild": LAB_FREQ_MULT_SEVERITY_MILD,
            }.get(severity, LAB_FREQ_MULT_SEVERITY_FALLBACK)
            freq_mod *= severity_mult
            # Near discharge: reduce routine labs
            if (
                day >= target_los - LAB_NEAR_DISCHARGE_DAY_OFFSET
                and state.inflammation_level < LAB_NEAR_DISCHARGE_INFLAMMATION_MAX
            ):
                freq_mod *= LAB_FREQ_MULT_NEAR_DISCHARGE
            # Weekend: reduce non-urgent labs
            if lab_time.weekday() >= 5:  # Saturday/Sunday
                freq_mod *= LAB_FREQ_MULT_WEEKEND
            # Stable patient: reduce after first week
            if day >= LAB_LATE_STAY_MIN_DAY and state.inflammation_level < LAB_LATE_STAY_INFLAMMATION_MAX:
                freq_mod *= LAB_FREQ_MULT_LATE_STAY_STABLE

            daily_orders = place_daily_lab_orders(
                protocol.model_dump(),
                patient.patient_id,
                encounter_id,
                day,
                lab_time,
                freq_mod,
                rng,
                ordered_by=attending_id,
            )
            all_orders.extend(daily_orders)

            # Imaging orders for day >= 1 (day=0 handled pre-loop in
            # simulate_inpatient_encounter). Counter threads from admission
            # call so IDs are unique across the full encounter.
            daily_imaging = place_imaging_orders(
                protocol,
                encounter_id,
                patient.patient_id,
                admission_time,
                day_index=day,
                severity=severity,
                rng=rng,
                sequence_counter=_img_seq,
            )
            all_orders.extend(daily_imaging)

        # Chronic condition monitoring labs (additional to disease protocol)
        if chronic_monitoring and day >= 1:
            chronic_lab_orders = _place_chronic_monitoring_orders(
                chronic_monitoring,
                patient.patient_id,
                day,
                admission_time,
                rng,
                encounter_id=encounter_id,
                ordered_by=attending_id,
            )
            all_orders.extend(chronic_lab_orders)

        # Lab results (with temporal lag for slow markers like CRP)
        lab_hour = lab_time.hour if "lab_time" in dir() else 6  # early morning default
        # J5 (Phase 2a): read every scenario flag (causes_myocardial_injury,
        # causes_vte, future additions) via one helper and splat with **flags
        # so every call site stays in sync. See physiology.engine docstring.
        # Phase 2b (2026-06-24): sibling helper medication_flags_from_context
        # detects chronic warfarin from current_medications AND in-hospital
        # warfarin orders >= 3 days old (loading-dose 3-day rule). Both
        # helpers spread as **flags so a new flag added to derive_lab_values
        # reaches this site without touching the call.
        _med_orders = [o for o in all_orders if o.order_type.value == "medication"]
        # Issue #2293: the same in-effect medication list drives INR generation
        # (the warfarin flag below) and result flagging / therapeutic ranges.
        _meds_in_effect = medications_in_effect(patient.current_medications, _med_orders, admission_time.date(), day)
        flags = {
            **scenario_flags_from_protocol(protocol),
            **medication_flags_from_context(
                patient,
                medication_orders=_med_orders,
                admission_date=admission_time.date(),
                current_day=day,
            ),
        }
        from clinosim.modules.physiology.engine import hba1c_latent_at

        _hba1c_latent = hba1c_latent_at(patient, admission_time + __import__("datetime").timedelta(days=day))
        # Issue #1988: on day 0 of a DKA encounter, resolve admission labs
        # against the pre-update state so the ABG HCO3 reflects the acute
        # presentation rather than ~1 day of recovery.
        _true_labs_state = _lab_state_pre_update if _lab_state_pre_update is not None else state
        true_labs = derive_lab_values(
            _true_labs_state,
            sex=patient.sex,
            age=patient.age,
            has_diabetes=has_diabetes,
            has_dyslipidemia=has_dyslipidemia,
            hour=lab_hour,
            hba1c_latent=_hba1c_latent,
            **flags,
        )  # noqa: E501

        # Apply temporal lag: CRP reflects inflammation from ~1 day ago
        if len(state_history) >= 2 and "CRP" in true_labs:
            lag_idx = max(0, len(state_history) - 2)
            lagged_state = state_history[lag_idx]
            lagged_labs = derive_lab_values(
                lagged_state,
                sex=patient.sex,
                age=patient.age,
                has_diabetes=has_diabetes,
                has_dyslipidemia=has_dyslipidemia,
                hour=lab_hour,
                hba1c_latent=_hba1c_latent,
                **flags,
            )  # noqa: E501
            true_labs["CRP"] = lagged_labs.get("CRP", true_labs["CRP"])

        # Expand panel orders (e.g. ABG → pH/pCO2/pO2/HCO3; CBC → WBC/Hb/Hct/Plt) into
        # component child lab orders. The parent is marked RESULTED (no scalar result →
        # no duplicate Observation). Children are kept *separate* from the master
        # parent stream so their RNG draws can run on a per-parent isolated sub-RNG
        # (see Pass 2 below), preventing panel-registry edits from cascading into
        # unrelated patients' cohorts (AD-16).
        _panel_children_by_parent: dict[str, list[Order]] = {}
        for order in all_orders:
            if order.order_type.value == "lab" and order.status == OrderStatus.PLACED:
                comps = lab_panel_components(order.display_name)
                if not comps:
                    continue
                children: list[Order] = []
                for comp_name in comps:
                    children.append(
                        Order(
                            order_id=f"{order.order_id}-{comp_name}",
                            patient_id=order.patient_id,
                            order_type=OrderType.LAB,
                            display_name=comp_name,
                            urgency=order.urgency,
                            clinical_intent=order.clinical_intent,
                            # Issue #871: forward the JA display alongside the EN.
                            clinical_intent_ja=order.clinical_intent_ja,
                            ordered_datetime=order.ordered_datetime,
                            ordered_by=order.ordered_by,
                            encounter_id=order.encounter_id,
                            status=OrderStatus.PLACED,
                        )
                    )
                _panel_children_by_parent[order.order_id] = children
                order.status = OrderStatus.RESULTED

        # The flat list (preserves insertion order so downstream serialisers, e.g.
        # _bb_labs in fhir_r4_adapter, retain a stable index for `lab-{enc}-{idx:04d}`).
        _panel_children: list[Order] = [c for kids in _panel_children_by_parent.values() for c in kids]
        all_orders.extend(_panel_children)
        _panel_child_ids = {c.order_id for c in _panel_children}

        # Two-pass lab-result generation (Pass 1 scalar/non-panel + Pass 2
        # panel children). Extracted to ``clinosim.simulator.lab_pipeline``
        # (Issue #552 PR A) — see that module's docstring for the RNG
        # contract and byte-neutrality guarantees.
        _day_results_start = len(all_lab_results)
        all_lab_results.extend(
            _run_lab_result_pipeline(
                all_orders,
                _panel_children_by_parent,
                _panel_child_ids,
                true_labs,
                patient,
                country_key,
                roster,
                hospital_state,
                hospital_ops,
                medications=_meds_in_effect,
            )
        )

        # Diagnosis update
        if day >= 1:
            # Issue #2240: only the results drawn today. A fixed window over
            # the whole stay missed CRP behind a large panel and re-counted
            # the same old result as new evidence on days without a draw.
            findings = _extract_findings(all_lab_results[_day_results_start:], disease_id, day)
            if findings:
                protocol_lr = (
                    protocol.likelihood_ratios
                    if hasattr(protocol, "likelihood_ratios") and protocol.likelihood_ratios
                    else None
                )  # noqa: E501
                protocol_diagnostic = protocol.diagnostic if hasattr(protocol, "diagnostic") else {}
                yaml_lr = protocol_diagnostic.get("likelihood_ratios") if protocol_diagnostic else None
                differential = update_differential(differential, findings, protocol_lr_table=yaml_lr or protocol_lr)

        # Archetype-specific order/treatment modifications (YAML-driven)
        archetype_data = protocol.course_archetypes.get(archetype, {}) if protocol.course_archetypes else {}
        order_mods = archetype_data.get("order_modifications", {})
        treatment_mods = archetype_data.get("treatment_modifications", {})

        # Check order/treatment modifications for this day (with ±1 day jitter for realism)
        day_key = f"day_{day}"
        # Also check adjacent days (in case the modification fires ±1 day early/late)
        day_keys_to_check = [day_key]
        if rng.random() < ARCHETYPE_DAY_SHIFT_PROBABILITY:  # ±1 day jitter for realism
            shift = int(rng.choice([-1, 1]))
            alt_key = f"day_{day + shift}"
            if alt_key in order_mods and day_key not in order_mods:
                day_keys_to_check = [alt_key]

        matched_order_key = None
        for dk in day_keys_to_check:
            if dk in order_mods:
                matched_order_key = dk
                break

        if matched_order_key:
            mod = order_mods[matched_order_key]
            # Add labs
            for lab_name in mod.get("add_labs", []):
                all_orders.append(
                    Order(
                        order_id=f"ORD-{encounter_id}-MOD-D{day}-{sanitize_id_token(lab_name, 5)}",
                        patient_id=patient.patient_id,
                        order_type=OrderType.LAB,
                        display_name=lab_name,
                        urgency="stat",
                        clinical_intent=f"Day {day} {archetype}: additional workup",
                        # Issue #871: JA display for JP SR reasonCode.text.
                        # `archetype` is a code identifier (sepsis/ards/etc.) —
                        # kept as-is; the shell is translated.
                        clinical_intent_ja=f"第{day}病日 {archetype}: 追加検査",
                        ordered_datetime=admission_time + timedelta(days=day, hours=10),
                        status=OrderStatus.PLACED,
                    )
                )
            # Add imaging
            for img_idx, img_name in enumerate(mod.get("add_imaging", [])):
                all_orders.append(
                    Order(
                        order_id=f"ORD-{encounter_id}-MOD-D{day}-IMG-{img_idx}",
                        patient_id=patient.patient_id,
                        order_type=OrderType.IMAGING,
                        display_name=img_name,
                        urgency="stat",
                        clinical_intent=f"Day {day} {archetype}: additional imaging",
                        # Issue #871: JA display for JP SR reasonCode.text.
                        clinical_intent_ja=f"第{day}病日 {archetype}: 追加画像検査",
                        ordered_datetime=admission_time + timedelta(days=day, hours=10),
                        status=OrderStatus.PLACED,
                    )
                )

        # Treatment modifications (same jitter logic)
        matched_tx_key = None
        for dk in day_keys_to_check:
            if dk in treatment_mods:
                matched_tx_key = dk
                break

        if matched_tx_key:
            mod = treatment_mods[matched_tx_key]
            # Stop medications
            for stop_idx, drug_name in enumerate(mod.get("stop", [])):
                all_orders.append(
                    Order(
                        order_id=(
                            f"ORD-{encounter_id}{MED_STOP_ORDER_ID_MARKER}"
                            f"D{day}-{stop_idx}-{sanitize_id_token(drug_name, 8)}"
                        ),
                        patient_id=patient.patient_id,
                        order_type=OrderType.MEDICATION,
                        display_name=f"DISCONTINUE: {drug_name}",
                        urgency="routine",
                        clinical_intent=f"Day {day} {archetype}: stop {drug_name}",
                        # Issue #871: JA display for JP SR reasonCode.text.
                        clinical_intent_ja=f"第{day}病日 {archetype}: {drug_name} 中止",
                        ordered_datetime=admission_time + timedelta(days=day, hours=10),
                        status=OrderStatus.PLACED,
                    )
                )
            # Start new medications or procedures
            start_meds = mod.get("start", {}).get(country_key, mod.get("start", []))
            if isinstance(start_meds, list):
                for med in start_meds:
                    if not isinstance(med, dict):
                        continue
                    drug = med.get("drug", "").strip()
                    proc = med.get("procedure", "").strip()
                    if drug:
                        # Daily-loop step medications sometimes carry device or
                        # therapy names disguised as drugs (NIV_BiPAP / CPAP /
                        # IPC / cardiac monitoring / etc.). Classify via the
                        # canonical treatment_classifier (single source of
                        # truth; J5 pattern prevention — this was C4-28's
                        # RM-6b sibling gap in).
                        display = f"{drug} {med.get('dose', '')}".strip()
                        _dc_order_type = classify_encounter_treatment(drug)
                        _is_medication = _dc_order_type == OrderType.MEDICATION
                        if _is_medication:
                            _order_id_prefix = f"ORD-{encounter_id}-START-D{day}-{sanitize_id_token(drug, 8)}"
                            _intent = f"Day {day} {archetype}: new medication"
                            _intent_ja = f"第{day}病日 {archetype}: 新規投薬"
                        else:
                            _order_id_prefix = f"ORD-{encounter_id}-DEV-D{day}-{sanitize_id_token(drug, 8)}"
                            _intent = f"Day {day} {archetype}: device / therapy"
                            _intent_ja = f"第{day}病日 {archetype}: 器材/治療"
                        all_orders.append(
                            Order(
                                order_id=_order_id_prefix,
                                patient_id=patient.patient_id,
                                order_type=_dc_order_type,
                                display_name=display,
                                urgency="urgent",
                                clinical_intent=_intent,
                                # Issue #871: JA display for JP SR reasonCode.text.
                                clinical_intent_ja=_intent_ja,
                                ordered_datetime=admission_time + timedelta(days=day, hours=10),
                                status=OrderStatus.PLACED,
                            )
                        )
                    elif proc:
                        # Procedure order (not a medication)
                        detail = med.get("detail", "")
                        display = f"{proc}" + (f" ({detail})" if detail else "")
                        all_orders.append(
                            Order(
                                order_id=f"ORD-{encounter_id}-PROC-D{day}-{sanitize_id_token(proc, 8)}",
                                patient_id=patient.patient_id,
                                order_type=OrderType.PROCEDURE,
                                display_name=display,
                                urgency="urgent",
                                clinical_intent=f"Day {day} {archetype}: new procedure",
                                # Issue #871: JA display for JP SR reasonCode.text.
                                clinical_intent_ja=f"第{day}病日 {archetype}: 新規処置",
                                ordered_datetime=admission_time + timedelta(days=day, hours=10),
                                status=OrderStatus.PLACED,
                            )
                        )
                    # Skip entries with neither drug nor procedure

        # Treatment escalation: if inflammation not improving by day 3, escalate
        # Issue #914: an inflammation-not-improving heuristic alone fired on
        # nearly every day-3 admission with mid-severity, producing meropenem
        # (or the disease's escalation agent) on ~34 % of pyelonephritis
        # encounters — real clinical escalation rate is <15 % (reserved for
        # culture ESBL / true 72 h non-defervescence). Each ``escalation``
        # entry may now carry an optional ``probability`` field (0.0-1.0);
        # when unset the pre-existing "always escalate on trigger" behavior
        # is preserved (byte-compat with disease YAMLs that predate this).
        if day == TREATMENT_ESCALATION_DAY and state.inflammation_level > TREATMENT_ESCALATION_INFLAMMATION_MIN:
            escalation_drugs = protocol.drugs.get("escalation", {}).get(country_key, [])
            if isinstance(escalation_drugs, dict):
                escalation_drugs = [escalation_drugs]
            for esc_drug in escalation_drugs:
                if not isinstance(esc_drug, dict):
                    continue
                _esc_prob = esc_drug.get("probability")
                if _esc_prob is not None and float(_esc_prob) < 1.0:
                    if rng.random() >= float(_esc_prob):
                        continue
                drug_name = esc_drug.get("drug", "")
                dose = esc_drug.get("dose", "")
                indication = esc_drug.get("indication", "no improvement")
                # Escalation entries carry a `drug` field but the value is
                # sometimes actually a procedure name (Vertebroplasty,
                # Hemodialysis, endoscopy, etc.). Route via the canonical
                # treatment_classifier (J5 pattern prevention).
                _esc_display = f"{drug_name} {dose}".strip()
                _esc_order_type = classify_escalation_treatment(esc_drug)
                all_orders.append(
                    Order(
                        order_id=f"ORD-{encounter_id}-ESC-D{day}-{sanitize_id_token(drug_name, 8)}",
                        encounter_id=encounter_id,
                        patient_id=patient.patient_id,
                        order_type=_esc_order_type,
                        order_code=esc_drug.get("code_yj") or esc_drug.get("code_rxnorm") or "",
                        display_name=_esc_display,
                        urgency="urgent",
                        clinical_intent=f"Escalation day {day}: {drug_name} ({indication})",
                        # Issue #871: JA display for JP SR reasonCode.text.
                        # `drug_name` and `indication` are kept as-is (may be
                        # EN or already-JA from disease YAML) — shell translated.
                        clinical_intent_ja=f"治療エスカレーション第{day}病日: {drug_name} ({indication})",
                        ordered_datetime=admission_time + timedelta(days=day, hours=10),
                        ordered_by=attending_id,
                        status=OrderStatus.PLACED,
                        route=esc_drug.get("route", "IV"),
                        # Issue #476: propagate authored localized dose
                        # instructions from YAML so the FHIR builder can emit
                        # them as country-scoped `dosageInstruction.text`.
                        dose_text_ja=esc_drug.get("dose_ja", ""),
                        dose_text_en=esc_drug.get("dose_en", ""),
                    )
                )

        # Medication administration (MAR)
        mars_today = _generate_mar(
            patient, all_orders, day, admission_time, department=department, roster=roster, rng=rng
        )  # noqa: E501
        all_mars.extend(mars_today)

        # Diet order (only when diet changes: NPO → clear liquid → soft → regular)
        if day == 0:
            diet = "NPO"
        elif day == 1 and state.inflammation_level > DIET_CLEAR_LIQUID_INFLAMMATION_THRESHOLD:
            diet = "clear_liquid"
        elif state.inflammation_level > DIET_SOFT_INFLAMMATION_THRESHOLD:
            diet = "soft_diet"
        else:
            diet = "regular_diet"
        if diet != prev_diet:
            all_orders.append(
                Order(
                    order_id=f"ORD-{encounter_id}-DIET-D{day}",
                    patient_id=patient.patient_id,
                    order_type=OrderType.DIET,
                    display_name=diet,
                    urgency="routine",
                    clinical_intent=f"Day {day} diet: {diet}",
                    # Issue #871: JA display for JP SR reasonCode.text.
                    clinical_intent_ja=f"第{day}病日 食事: {diet}",
                    ordered_datetime=admission_time + timedelta(days=day, hours=7),
                    ordered_by=attending_id,
                    status=OrderStatus.PLACED,
                )
            )
            prev_diet = diet

        # Vitals
        ward_nurse_id = assign_staff("medication_administration", department, roster, rng).get(
            "administering_nurse", FALLBACK_NURSE_ID
        )  # noqa: E501
        vitals_country = "JP" if country_key == "japan" else "US"
        vitals_today = _generate_vitals(
            state,
            patient,
            day,
            admission_time,
            rng,
            disease_id=disease_id,
            nurse_id=ward_nurse_id,
            country=vitals_country,
        )  # noqa: E501
        all_vitals.extend(vitals_today)
        # Issue #2085: PRN analgesia / benzodiazepines on demand from today's
        # pain scores and autonomic state.
        all_mars.extend(generate_prn_administrations(all_orders, vitals_today, state, prn_last_given))

        # Daily I/O record
        io_record = _generate_daily_io(state, patient, day, admission_time, rng)
        all_io.append(io_record)

        # ADL assessment (admission, weekly, discharge approach)
        adl = _generate_adl_assessment(state, patient, day, admission_time, rng)
        if adl:
            all_adl.append(adl)

        # Complications
        comp_list = protocol.complications if protocol.complications else []
        if comp_list and day >= 1:
            triggered = evaluate_complications(
                day,
                state,
                patient,
                comp_list,
                active_complications,
                rng,
                severity=severity,
                context=_complication_context(
                    patient,
                    all_orders,
                    admission_time,
                    icu_day=icu_transferred_day_local if icu_transferred else None,
                    intubated_day=intubated_day,
                    surgery_day=surgery[0] if surgery else None,
                    procedures=list(prior_procedures or []) + escalation_procedures,
                    dvt_prophylaxis=dvt_prophylaxis_planned,
                ),
            )
            for comp in triggered:
                for var, delta in comp.get("state_impact", {}).items():
                    apply_state_delta(state, var, delta)
                comp_name = comp.get("name", "unknown")
                # Phase 1a: record the onset day + a canonical noon-of-day
                # timestamp so downstream (narrative context filter,
                # hospital_course_extractor ordering, future FHIR Condition
                # .onsetDateTime emit) knows WHEN the complication fired.
                # The daily loop is per-day, not per-hour, so noon is used
                # as a stable within-day anchor.
                onset_dt = admission_time + timedelta(days=day)
                onset_dt = onset_dt.replace(hour=12, minute=0, second=0, microsecond=0)
                complications_occurred.append(
                    build_complication(
                        name=comp_name,
                        onset_day=day,
                        onset_datetime=onset_dt.isoformat(),
                        source="daily_loop",
                    )
                )
                if "icu_transfer" in comp.get("actions", []):
                    if not icu_transferred:
                        # C5-22: capture day of transfer for
                        # Encounter.classHistory. First trigger wins;
                        # subsequent ICU-triggering complications on later
                        # days do not overwrite (the patient is already in
                        # ICU by then).
                        icu_transferred_day_local = day
                    icu_transferred = True
                # Cancel contraindicated meds when AKI develops as complication
                if comp_name == "acute_kidney_injury":
                    for o in all_orders:
                        if o.order_type == OrderType.MEDICATION and o.status == OrderStatus.PLACED:
                            if "metformin" in (o.display_name or "").lower():
                                o.status = OrderStatus.CANCELLED

        # State-driven airway / ICU escalation (Issue #2091): intubation on the
        # day the airway threshold is crossed, ICU transfer for airway or shock.
        if not intubated and airway_escalation_needed(state):
            intubated = True
            intubated_day = day
            escalation_procedures.append(
                build_intubation_procedure(
                    patient.patient_id,
                    encounter_id,
                    admission_time + timedelta(days=day, hours=AIRWAY_ESCALATION_HOUR),
                    "JP" if country_key == "japan" else "US",
                    f"PROC-{patient.patient_id}-AIR{day:02d}",
                )
            )
        if not icu_transferred and icu_escalation_needed(state):
            icu_transferred_day_local = day
            icu_transferred = True

        # Mortality (disease-specific rate from YAML benchmarks)
        benchmark_mortality = protocol.outcome_benchmarks.get(country_key, {}).get("in_hospital_mortality", 0.0)
        if _evaluate_mortality(
            state,
            patient,
            severity=severity,
            day=day,
            rng=rng,
            disease_mortality_rate=benchmark_mortality,
            target_los=target_los,
            # Issue #2098: worst consciousness / oxygenation so far, relative to
            # the disease's presentation mix (keeps the benchmark average).
            state_relative_risk=mortality_state_multiplier(
                max(s.consciousness_impairment for s in state_history),
                max(s.oxygenation_impairment for s in state_history),
            )
            / expected_mortality_multiplier,
        ):
            death_occurred = True
            break

        # Early discharge: if state-based criteria met before target_los
        # (not for protocols whose recovery the physiology does not model,
        # e.g. psychiatric admissions, Issue #2132).
        if day >= min_los and not death_occurred and getattr(protocol, "state_based_discharge", True):
            if _check_discharge_ready(state, day, country_key, symptom_floor):
                break  # actual_los = day + 1

        if day + 1 >= los_ceiling:
            if not extend_stay_for_symptoms(state, los_ceiling, max_los, symptom_floor):
                break
            los_ceiling += 1

    try:
        actual_los = day + 1
    except NameError:
        actual_los = max(1, target_los)

    # C7b (#1100): drug_safety gate on post-admission MEDICATION Orders.
    # ``admission_orders`` were gated at admission time; anything the
    # daily loop appended afterwards (treatment_mod step-up meds,
    # complication-triggered add-ons) has never been checked. Partition
    # ``all_orders`` into (admission, new) and route the new ones through
    # the general gate, seeded with home + admission-accepted MEDICATION
    # names so a mid-encounter Aspirin request against an admission-time
    # Enoxaparin is skipped / substituted.
    from clinosim.simulator.medication_pipeline import (
        apply_drug_safety_gate_to_orders,
    )

    _admission_len = len(admission_orders)
    _pre_new = all_orders[:_admission_len]
    _new_orders = all_orders[_admission_len:]
    if _new_orders:
        _accepted = [o.display_name for o in _pre_new if o.order_type == OrderType.MEDICATION and o.display_name]
        _gated_new = apply_drug_safety_gate_to_orders(
            _new_orders,
            patient=patient,
            encounter_id=admission_orders[0].encounter_id if admission_orders else "",
            ordered_datetime=admission_time,
            attending_id=attending_id,
            protocol=protocol,
            country=country_key,
            already_accepted_meds=_accepted,
        )
        all_orders = _pre_new + _gated_new

    return {
        "orders": all_orders,
        "lab_results": all_lab_results,
        "vitals": all_vitals,
        "mars": all_mars,
        "io_records": all_io,
        "adl_assessments": all_adl,
        "state_history": state_history,
        "complications": complications_occurred,
        "death_occurred": death_occurred,
        "icu_transferred": icu_transferred,
        "icu_transferred_day": icu_transferred_day_local,  # C5-22
        "escalation_procedures": escalation_procedures,
        "differential": differential,
        "actual_los": actual_los,
    }


# ============================================================
# Discharge prescription
# ============================================================


# ============================================================
# Findings extraction for diagnosis
# ============================================================


def _extract_findings(
    lab_results: list[OrderResult],
    disease_id: str,
    day: int,
) -> list[tuple[str, bool]]:
    """Extract diagnostic findings from the day's lab results for Bayesian update."""
    findings: list[tuple[str, bool]] = []

    for r in lab_results:
        if r.lab_name == "CRP":
            v = r.value if isinstance(r.value, (int, float)) else 0
            findings.append(("crp_above_100", v > 100))
        elif r.lab_name == "WBC":
            v = r.value if isinstance(r.value, (int, float)) else 0
            findings.append(("wbc_elevated", v > 15000))

    # Day 1: imaging findings (simulated)
    if day == 1 and disease_id == "bacterial_pneumonia":
        findings.append(("chest_xray_consolidation", True))
        findings.append(("procalcitonin_elevated", True))

    return findings
