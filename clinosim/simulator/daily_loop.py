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
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

import numpy as np

from clinosim.codes.drugs import has_drug, protocol_drug_name
from clinosim.countries import country_code
from clinosim.locale.i18n import t
from clinosim.locale.localized import language_slot
from clinosim.modules._shared import MED_STOP_ORDER_ID_MARKER, sanitize_id_token
from clinosim.modules.clinical_course._complication_risk_conditions import ComplicationContext, in_drug_class
from clinosim.modules.clinical_course.engine import (
    apply_diagnosis_modifier,
    compute_diagnosis_effectiveness,
    evaluate_complications,
    get_daily_directive,
    natural_recovery_directive,
)
from clinosim.modules.diagnosis.engine import update_differential
from clinosim.modules.disease.protocol import DiseaseProtocol
from clinosim.modules.observation.engine import canonical_lab_name, lab_panel_components, medications_in_effect
from clinosim.modules.observation.order_routing import lab_order_targets
from clinosim.modules.order.engine import (
    place_daily_lab_orders,
    place_imaging_orders,
    protocol_drug_order_code,
    protocol_drug_order_code_system,
)
from clinosim.modules.order.treatment_classifier import (
    classify_encounter_treatment,
    classify_escalation_treatment,
)
from clinosim.modules.physiology.engine import (
    apply_state_delta,
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
from clinosim.simulator.diagnosis_rules import day1_imaging_findings, lab_finding_rules
from clinosim.simulator.discharge_gate import (
    _check_discharge_ready,
    _evaluate_mortality,
    expected_state_multiplier,
    extend_stay_for_symptoms,
    mortality_state_multiplier,
)
from clinosim.simulator.lab_pipeline import _run_lab_result_pipeline, patient_true_labs
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
        if in_drug_class(o.display_name or "", "antibiotic")
    ]
    return ComplicationContext(
        icu_day=icu_day,
        intubated_day=intubated_day,
        surgery_day=surgery_day,
        antibiotic_start_day=min(antibiotic_days) if antibiotic_days else None,
        medications={o.display_name or "" for o in meds},
        home_medications={m.drug_name or "" for m in getattr(patient, "current_medications", []) or []},
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


@dataclass
class DailyLoopResult:
    """Everything the day-by-day loop generated for one inpatient stay."""

    orders: list[Order]
    lab_results: list[OrderResult]
    vitals: list[VitalSignRecord]
    mars: list[MedicationAdministration]
    io_records: list
    adl_assessments: list
    state_history: list[PhysiologicalState]
    # Phase 1a schema: entries are dicts with onset_day / onset_datetime /
    # source (see clinosim.simulator.complications for the canonical shape);
    # typed as CIFPatientRecord.complications_occurred.
    complications: list[dict[str, Any] | str]
    death_occurred: bool
    icu_transferred: bool
    icu_transferred_day: int  # C5-22: day of ICU transfer, -1 when none
    escalation_procedures: list  # Issue #2091: state-driven intubation records
    differential: Any
    actual_los: int


@dataclass
class _Stay:
    """The fixed inputs of one stay's daily loop."""

    patient: PatientProfile
    disease_id: str
    protocol: DiseaseProtocol
    archetype: str
    admission_time: datetime
    target_los: int
    healthcare: HealthcareSystemConfig
    roster: StaffRoster
    rng: np.random.Generator
    chronic_monitoring: list[dict] | None
    country_key: str
    min_los: int
    hospital_state: Any
    hospital_ops: dict | None
    attending_id: str
    department: str
    severity: str
    encounter_id: str
    imaging_seq: dict[str, int]
    symptom_floor: dict[str, float] | None
    max_los: int | None
    surgery: tuple[int, float] | None
    prior_procedures: list | None

    @property
    def country(self) -> str:
        return country_code(self.country_key)


@dataclass
class _Run:
    """What the daily loop accumulates and carries from one day to the next."""

    state: PhysiologicalState
    differential: Any
    orders: list[Order]
    dvt_prophylaxis_planned: bool
    lab_results: list[OrderResult] = field(default_factory=list)
    vitals: list[VitalSignRecord] = field(default_factory=list)
    mars: list[MedicationAdministration] = field(default_factory=list)
    prn_last_given: dict[str, datetime] = field(default_factory=dict)  # Issue #2085: PRN order -> last dose time
    io_records: list = field(default_factory=list)
    adl_assessments: list = field(default_factory=list)
    state_history: list[PhysiologicalState] = field(default_factory=list)
    active_complications: set[str] = field(default_factory=set)
    complications: list[dict[str, Any] | str] = field(default_factory=list)
    death_occurred: bool = False
    icu_transferred: bool = False
    icu_transferred_day: int = -1  # C5-22: day of ICU transfer
    intubated: bool = False
    intubated_day: int | None = None  # Issue #2101: complication context
    escalation_procedures: list = field(default_factory=list)  # Issue #2091: state-driven intubation records
    prev_diet: str = ""  # last diet ordered for this patient
    # Admission orders, including the components an admission panel order
    # was expanded into (Issue #2582); the drug-safety gate checks the rest.
    admission_order_ids: set[str] = field(default_factory=set)
    lab_time: datetime | None = None  # the most recent morning lab draw (none before day 1)


def _escalate_on_arrival(stay: _Stay, run: _Run) -> None:
    """Presentation already beyond the airway / ICU thresholds (e.g. GCS <= 8 on
    arrival): intubate and transfer on the admission day."""
    if airway_escalation_needed(run.state):
        run.intubated = True
        run.intubated_day = 0
        run.escalation_procedures.append(
            build_intubation_procedure(
                stay.patient.patient_id,
                stay.encounter_id,
                stay.admission_time + timedelta(hours=1),
                stay.country,
                f"PROC-{stay.patient.patient_id}-AIR00",
            )
        )
    if icu_escalation_needed(run.state):
        run.icu_transferred = True
        run.icu_transferred_day = 0


def _advance_state(stay: _Stay, run: _Run, day: int) -> PhysiologicalState | None:
    """Apply the day's course directive, dampened when the working diagnosis is
    wrong, plus natural recovery. Returns the pre-update state on DKA day 0."""
    patient, protocol = stay.patient, stay.protocol
    directive = get_daily_directive(
        stay.archetype,
        day,
        patient.physiological_profile,
        protocol_archetypes=protocol.course_archetypes or None,
        age=patient.age,
        rng=stay.rng,
    )

    # Phase 1: Dampen recovery if diagnosis is wrong
    dx_confidence = 0.0
    working_dx = None
    if run.differential.top_candidate:
        dx_confidence = run.differential.top_candidate.probability
        working_dx = run.differential.top_candidate.disease_code
    dx_difficulty = (protocol.diagnostic or {}).get("diagnostic_difficulty", 0.3)
    effectiveness = compute_diagnosis_effectiveness(
        working_dx,
        stay.disease_id,
        dx_confidence,
        day,
        diagnostic_difficulty=dx_difficulty,
    )
    directive = apply_diagnosis_modifier(
        directive,
        effectiveness,
        current_volume=run.state.volume_status,
        current_ph=run.state.ph_status,
    )

    # Phase 2: Natural recovery (small baseline healing)
    nat_directive = natural_recovery_directive(
        day,
        stay.disease_id,
        stay.severity,
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
    lab_state_pre_update = deepcopy(run.state) if (day == 0 and stay.disease_id == "diabetic_ketoacidosis") else None
    run.state = update(run.state, directive, timedelta(days=1))
    if stay.symptom_floor:
        apply_symptom_floor(run.state, stay.symptom_floor)
    apply_postoperative_pain(run.state, day, stay.surgery)
    run.state_history.append(deepcopy(run.state))
    return lab_state_pre_update


def _place_daily_lab_and_imaging_orders(stay: _Stay, run: _Run, day: int) -> None:
    """Daily lab orders (from Day 1) with context-dependent frequency, and the
    day's imaging orders."""
    rng, state = stay.rng, run.state
    # Morning lab draw: 05:30-07:00 with jitter
    lab_hour = LAB_MORNING_HOUR
    lab_min = int(rng.integers(LAB_MIN_START, LAB_MIN_END_EXCLUSIVE))
    if rng.random() < LAB_EARLY_MORNING_PROBABILITY:
        lab_hour = LAB_EARLY_MORNING_HOUR
        lab_min = int(rng.integers(LAB_EARLY_MORNING_MIN_START, LAB_EARLY_MORNING_MIN_END_EXCLUSIVE))
    lab_time = datetime(
        stay.admission_time.year,
        stay.admission_time.month,
        stay.admission_time.day,
        lab_hour,
        lab_min,
    ) + timedelta(days=day)
    run.lab_time = lab_time

    # Context-dependent lab frequency modulation
    freq_mod = stay.healthcare.lab_frequency_multiplier
    # Severity: severe patients get more frequent labs, mild get fewer
    severity_mult = {
        "severe": LAB_FREQ_MULT_SEVERITY_SEVERE,
        "moderate": LAB_FREQ_MULT_SEVERITY_MODERATE,
        "mild": LAB_FREQ_MULT_SEVERITY_MILD,
    }.get(stay.severity, LAB_FREQ_MULT_SEVERITY_FALLBACK)
    freq_mod *= severity_mult
    # Near discharge: reduce routine labs
    if (
        day >= stay.target_los - LAB_NEAR_DISCHARGE_DAY_OFFSET
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
        stay.protocol.model_dump(),
        stay.patient.patient_id,
        stay.encounter_id,
        day,
        lab_time,
        freq_mod,
        rng,
        ordered_by=stay.attending_id,
    )
    run.orders.extend(daily_orders)

    # Imaging orders for day >= 1 (day=0 handled pre-loop in
    # simulate_inpatient_encounter). Counter threads from admission
    # call so IDs are unique across the full encounter.
    daily_imaging = place_imaging_orders(
        stay.protocol,
        stay.encounter_id,
        stay.patient.patient_id,
        stay.admission_time,
        day_index=day,
        severity=stay.severity,
        rng=rng,
        sequence_counter=stay.imaging_seq,
    )
    run.orders.extend(daily_imaging)


def _expand_panel_orders(orders: list[Order]) -> dict[str, list[Order]]:
    """Expand placed panel orders (e.g. ABG → pH/pCO2/pO2/HCO3; CBC →
    WBC/Hb/Hct/Plt) into component child lab orders, keyed by parent id.

    The children carry the panel as ``panel_key``, so the FHIR builder emits
    them as one panel ServiceRequest with the component results under it; the
    caller drops the parent order, which would otherwise be a second, empty
    order for the same specimen (Issue #2582). Children are kept *separate*
    from the master parent stream so their RNG draws can run on a per-parent
    isolated sub-RNG (see Pass 2 in lab_pipeline), preventing panel-registry
    edits from cascading into unrelated patients' cohorts (AD-16).
    """
    children_by_parent: dict[str, list[Order]] = {}
    for order in orders:
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
                        panel_key=canonical_lab_name(order.display_name),
                    )
                )
            children_by_parent[order.order_id] = children
            order.status = OrderStatus.RESULTED
    return children_by_parent


def _result_labs(stay: _Stay, run: _Run, day: int, lab_state_pre_update: PhysiologicalState | None) -> int:
    """Result every placed lab order (with temporal lag for slow markers like
    CRP). Returns the index of the first result drawn today."""
    patient, admission_time = stay.patient, stay.admission_time
    lab_hour = run.lab_time.hour if run.lab_time is not None else 6  # early morning default
    # J5 (Phase 2a): read every scenario flag (causes_myocardial_injury,
    # causes_vte, future additions) via one helper and splat with **flags
    # so every call site stays in sync. See physiology.engine docstring.
    # Phase 2b (2026-06-24): sibling helper medication_flags_from_context
    # detects chronic warfarin from current_medications AND in-hospital
    # warfarin orders >= 3 days old (loading-dose 3-day rule). Both
    # helpers spread as **flags so a new flag added to derive_lab_values
    # reaches this site without touching the call.
    med_orders = [o for o in run.orders if o.order_type.value == "medication"]
    # Issue #2293: the same in-effect medication list drives INR generation
    # (the warfarin flag below) and result flagging / therapeutic ranges.
    meds_in_effect = medications_in_effect(patient.current_medications, med_orders, admission_time.date(), day)
    flags = {
        **scenario_flags_from_protocol(stay.protocol),
        **medication_flags_from_context(
            patient,
            medication_orders=med_orders,
            admission_date=admission_time.date(),
            current_day=day,
        ),
    }
    # Issue #1988: on day 0 of a DKA encounter, resolve admission labs
    # against the pre-update state so the ABG HCO3 reflects the acute
    # presentation rather than ~1 day of recovery.
    true_labs_state = lab_state_pre_update if lab_state_pre_update is not None else run.state
    lab_at = admission_time + timedelta(days=day)
    true_labs = patient_true_labs(true_labs_state, patient, lab_at, flags, hour=lab_hour)

    # Apply temporal lag: CRP reflects inflammation from ~1 day ago
    if len(run.state_history) >= 2 and "CRP" in true_labs:
        lag_idx = max(0, len(run.state_history) - 2)
        lagged_state = run.state_history[lag_idx]
        lagged_labs = patient_true_labs(lagged_state, patient, lab_at, flags, hour=lab_hour)
        true_labs["CRP"] = lagged_labs.get("CRP", true_labs["CRP"])

    panel_children_by_parent = _expand_panel_orders(run.orders)
    # The flat list (preserves insertion order so downstream serialisers, e.g.
    # _bb_labs in fhir_r4_adapter, retain a stable index for `lab-{enc}-{idx:04d}`).
    panel_children: list[Order] = [c for kids in panel_children_by_parent.values() for c in kids]
    if panel_children_by_parent:
        # Each expanded panel order is replaced in place by its components.
        run.orders = [c for o in run.orders for c in panel_children_by_parent.get(o.order_id, [o])]
        for parent_id, children in panel_children_by_parent.items():
            if parent_id in run.admission_order_ids:
                run.admission_order_ids.update(c.order_id for c in children)
    panel_child_ids = {c.order_id for c in panel_children}

    # Two-pass lab-result generation (Pass 1 scalar/non-panel + Pass 2
    # panel children). Extracted to ``clinosim.simulator.lab_pipeline``
    # (Issue #552 PR A) — see that module's docstring for the RNG
    # contract and byte-neutrality guarantees.
    day_results_start = len(run.lab_results)
    run.lab_results.extend(
        _run_lab_result_pipeline(
            run.orders,
            panel_children_by_parent,
            panel_child_ids,
            true_labs,
            patient,
            stay.country_key,
            stay.roster,
            stay.hospital_state,
            stay.hospital_ops,
            medications=meds_in_effect,
        )
    )
    return day_results_start


def _update_diagnosis(stay: _Stay, run: _Run, day: int, day_results_start: int) -> None:
    # Issue #2240: only the results drawn today. A fixed window over
    # the whole stay missed CRP behind a large panel and re-counted
    # the same old result as new evidence on days without a draw.
    findings = _extract_findings(run.lab_results[day_results_start:], stay.disease_id, day)
    if findings:
        protocol = stay.protocol
        protocol_lr = (
            protocol.likelihood_ratios
            if hasattr(protocol, "likelihood_ratios") and protocol.likelihood_ratios
            else None
        )  # noqa: E501
        protocol_diagnostic = protocol.diagnostic if hasattr(protocol, "diagnostic") else {}
        yaml_lr = protocol_diagnostic.get("likelihood_ratios") if protocol_diagnostic else None
        run.differential = update_differential(run.differential, findings, protocol_lr_table=yaml_lr or protocol_lr)


def _apply_archetype_modifications(stay: _Stay, run: _Run, day: int) -> None:
    """Archetype-specific order/treatment modifications (YAML-driven)."""
    protocol, archetype = stay.protocol, stay.archetype
    archetype_data = protocol.course_archetypes.get(archetype, {}) if protocol.course_archetypes else {}
    order_mods = archetype_data.get("order_modifications", {})
    treatment_mods = archetype_data.get("treatment_modifications", {})

    # Check order/treatment modifications for this day (with ±1 day jitter for realism)
    day_key = f"day_{day}"
    # Also check adjacent days (in case the modification fires ±1 day early/late)
    day_keys_to_check = [day_key]
    if stay.rng.random() < ARCHETYPE_DAY_SHIFT_PROBABILITY:  # ±1 day jitter for realism
        shift = int(stay.rng.choice([-1, 1]))
        alt_key = f"day_{day + shift}"
        if alt_key in order_mods and day_key not in order_mods:
            day_keys_to_check = [alt_key]

    matched_order_key = next((dk for dk in day_keys_to_check if dk in order_mods), None)
    if matched_order_key:
        _add_archetype_workup(stay, run, day, order_mods[matched_order_key])

    # Treatment modifications (same jitter logic)
    matched_tx_key = next((dk for dk in day_keys_to_check if dk in treatment_mods), None)
    if matched_tx_key:
        mod = treatment_mods[matched_tx_key]
        _stop_archetype_medications(stay, run, day, mod)
        _start_archetype_treatments(stay, run, day, mod)


def _add_archetype_workup(stay: _Stay, run: _Run, day: int, mod: dict) -> None:
    encounter_id, archetype = stay.encounter_id, stay.archetype
    ordered_at = stay.admission_time + timedelta(days=day, hours=10)
    # Add labs. An entry may route to imaging, to several component labs, or
    # to nothing (a vital sign) — see observation/order_routing.py (Issue #2583).
    for lab_name in mod.get("add_labs", []):
        lab_token = sanitize_id_token(lab_name, 5)
        targets = lab_order_targets(lab_name)
        for idx, target in enumerate(targets):
            if target.order_type == OrderType.IMAGING:
                order_id = f"ORD-{encounter_id}-MOD-D{day}-IMG-L{lab_token}"
                intent_key = "order_intent.archetype_imaging"
            else:
                order_id = f"ORD-{encounter_id}-MOD-D{day}-{lab_token}" + (f"-{idx}" if len(targets) > 1 else "")
                intent_key = "order_intent.archetype_workup"
            run.orders.append(
                Order(
                    order_id=order_id,
                    patient_id=stay.patient.patient_id,
                    order_type=target.order_type,
                    display_name=target.name,
                    urgency="stat",
                    clinical_intent=t(intent_key, "en", day=day, archetype=archetype),
                    # Issue #871: JA display for JP SR reasonCode.text.
                    # `archetype` is a code identifier (sepsis/ards/etc.) —
                    # kept as-is; the shell is translated.
                    clinical_intent_ja=t(intent_key, "ja", day=day, archetype=archetype),
                    ordered_datetime=ordered_at,
                    status=OrderStatus.PLACED,
                )
            )
    # Add imaging
    for img_idx, img_name in enumerate(mod.get("add_imaging", [])):
        run.orders.append(
            Order(
                order_id=f"ORD-{encounter_id}-MOD-D{day}-IMG-{img_idx}",
                patient_id=stay.patient.patient_id,
                order_type=OrderType.IMAGING,
                display_name=img_name,
                urgency="stat",
                clinical_intent=t("order_intent.archetype_imaging", "en", day=day, archetype=archetype),
                # Issue #871: JA display for JP SR reasonCode.text.
                clinical_intent_ja=t("order_intent.archetype_imaging", "ja", day=day, archetype=archetype),
                ordered_datetime=ordered_at,
                status=OrderStatus.PLACED,
            )
        )


def _stop_archetype_medications(stay: _Stay, run: _Run, day: int, mod: dict) -> None:
    encounter_id, archetype = stay.encounter_id, stay.archetype
    for stop_idx, drug_name in enumerate(mod.get("stop", [])):
        run.orders.append(
            Order(
                order_id=(
                    f"ORD-{encounter_id}{MED_STOP_ORDER_ID_MARKER}D{day}-{stop_idx}-{sanitize_id_token(drug_name, 8)}"
                ),
                patient_id=stay.patient.patient_id,
                order_type=OrderType.MEDICATION,
                display_name=f"DISCONTINUE: {drug_name}",
                urgency="routine",
                clinical_intent=t("order_intent.archetype_stop", "en", day=day, archetype=archetype, drug=drug_name),
                # Issue #871: JA display for JP SR reasonCode.text.
                clinical_intent_ja=t("order_intent.archetype_stop", "ja", day=day, archetype=archetype, drug=drug_name),
                ordered_datetime=stay.admission_time + timedelta(days=day, hours=10),
                status=OrderStatus.PLACED,
            )
        )


def _start_archetype_treatments(stay: _Stay, run: _Run, day: int, mod: dict) -> None:
    """Start new medications or procedures."""
    encounter_id, archetype = stay.encounter_id, stay.archetype
    start_meds = mod.get("start", {}).get(stay.country_key, mod.get("start", []))
    if not isinstance(start_meds, list):
        return
    for med in start_meds:
        if not isinstance(med, dict):
            continue
        drug = protocol_drug_name(med).strip()
        proc = med.get("procedure", "").strip()
        if drug:
            # Daily-loop step medications sometimes carry device or
            # therapy names disguised as drugs (NIV_BiPAP / CPAP /
            # IPC / cardiac monitoring / etc.). Classify via the
            # canonical treatment_classifier (single source of
            # truth; J5 pattern prevention — this was C4-28's
            # RM-6b sibling gap in).
            display = f"{drug} {med.get('dose', '')}".strip()
            order_type = classify_encounter_treatment(drug)
            if order_type == OrderType.MEDICATION:
                order_id = f"ORD-{encounter_id}-START-D{day}-{sanitize_id_token(drug, 8)}"
                intent_key = "order_intent.archetype_new_medication"
            else:
                order_id = f"ORD-{encounter_id}-DEV-D{day}-{sanitize_id_token(drug, 8)}"
                intent_key = "order_intent.archetype_device"
            run.orders.append(
                Order(
                    order_id=order_id,
                    patient_id=stay.patient.patient_id,
                    order_type=order_type,
                    display_name=display,
                    urgency="urgent",
                    clinical_intent=t(intent_key, "en", day=day, archetype=archetype),
                    # Issue #871: JA display for JP SR reasonCode.text.
                    clinical_intent_ja=t(intent_key, "ja", day=day, archetype=archetype),
                    ordered_datetime=stay.admission_time + timedelta(days=day, hours=10),
                    status=OrderStatus.PLACED,
                )
            )
        elif proc:
            # Procedure order (not a medication)
            detail = med.get("detail", "")
            display = f"{proc}" + (f" ({detail})" if detail else "")
            run.orders.append(
                Order(
                    order_id=f"ORD-{encounter_id}-PROC-D{day}-{sanitize_id_token(proc, 8)}",
                    patient_id=stay.patient.patient_id,
                    order_type=OrderType.PROCEDURE,
                    display_name=display,
                    urgency="urgent",
                    clinical_intent=t("order_intent.archetype_procedure", "en", day=day, archetype=archetype),
                    # Issue #871: JA display for JP SR reasonCode.text.
                    clinical_intent_ja=t("order_intent.archetype_procedure", "ja", day=day, archetype=archetype),
                    ordered_datetime=stay.admission_time + timedelta(days=day, hours=10),
                    status=OrderStatus.PLACED,
                )
            )
        # Skip entries with neither drug nor procedure


def _escalate_treatment(stay: _Stay, run: _Run, day: int) -> None:
    """Treatment escalation: inflammation not improving by day 3.

    Issue #914: an inflammation-not-improving heuristic alone fired on
    nearly every day-3 admission with mid-severity, producing meropenem
    (or the disease's escalation agent) on ~34 % of pyelonephritis
    encounters — real clinical escalation rate is <15 % (reserved for
    culture ESBL / true 72 h non-defervescence). Each ``escalation``
    entry may now carry an optional ``probability`` field (0.0-1.0);
    when unset the pre-existing "always escalate on trigger" behavior
    is preserved (byte-compat with disease YAMLs that predate this).
    """
    encounter_id, country_key = stay.encounter_id, stay.country_key
    escalation_drugs = stay.protocol.drugs.get("escalation", {}).get(country_key, [])
    if isinstance(escalation_drugs, dict):
        escalation_drugs = [escalation_drugs]
    for esc_drug in escalation_drugs:
        if not isinstance(esc_drug, dict):
            continue
        esc_prob = esc_drug.get("probability")
        if esc_prob is not None and float(esc_prob) < 1.0:
            if stay.rng.random() >= float(esc_prob):
                continue
        drug_name = protocol_drug_name(esc_drug) or str(esc_drug.get("procedure") or "")
        dose = esc_drug.get("dose", "")
        indication = esc_drug.get("indication", "no improvement")
        # Escalation entries carry a `drug` field but the value is
        # sometimes actually a procedure name (Vertebroplasty,
        # Hemodialysis, endoscopy, etc.). Route via the canonical
        # treatment_classifier (J5 pattern prevention).
        run.orders.append(
            Order(
                order_id=f"ORD-{encounter_id}-ESC-D{day}-{sanitize_id_token(drug_name, 8)}",
                encounter_id=encounter_id,
                patient_id=stay.patient.patient_id,
                order_type=classify_escalation_treatment(esc_drug),
                order_code=protocol_drug_order_code(esc_drug, country_key),
                order_code_system=protocol_drug_order_code_system(esc_drug, country_key),
                display_name=f"{drug_name} {dose}".strip(),
                urgency="urgent",
                clinical_intent=t("order_intent.escalation", "en", day=day, drug=drug_name, indication=indication),
                # Issue #871: JA display for JP SR reasonCode.text.
                # `drug_name` and `indication` are kept as-is (may be
                # EN or already-JA from disease YAML) — shell translated.
                clinical_intent_ja=t("order_intent.escalation", "ja", day=day, drug=drug_name, indication=indication),
                ordered_datetime=stay.admission_time + timedelta(days=day, hours=10),
                ordered_by=stay.attending_id,
                status=OrderStatus.PLACED,
                route=esc_drug.get("route", "IV"),
                # Issue #476: propagate authored localized dose
                # instructions from YAML so the FHIR builder can emit
                # them as country-scoped `dosageInstruction.text`.
                dose_text_ja=language_slot(esc_drug.get("dose_text"), "ja"),
                dose_text_en=language_slot(esc_drug.get("dose_text"), "en"),
            )
        )


def _order_diet(stay: _Stay, run: _Run, day: int) -> None:
    """Diet order (only when diet changes: NPO → clear liquid → soft → regular)."""
    if day == 0:
        diet = "NPO"
    elif day == 1 and run.state.inflammation_level > DIET_CLEAR_LIQUID_INFLAMMATION_THRESHOLD:
        diet = "clear_liquid"
    elif run.state.inflammation_level > DIET_SOFT_INFLAMMATION_THRESHOLD:
        diet = "soft_diet"
    else:
        diet = "regular_diet"
    if diet != run.prev_diet:
        run.orders.append(
            Order(
                order_id=f"ORD-{stay.encounter_id}-DIET-D{day}",
                patient_id=stay.patient.patient_id,
                order_type=OrderType.DIET,
                display_name=diet,
                urgency="routine",
                clinical_intent=t("order_intent.diet", "en", day=day, diet=diet),
                # Issue #871: JA display for JP SR reasonCode.text.
                clinical_intent_ja=t("order_intent.diet", "ja", day=day, diet=diet),
                ordered_datetime=stay.admission_time + timedelta(days=day, hours=7),
                ordered_by=stay.attending_id,
                status=OrderStatus.PLACED,
            )
        )
        run.prev_diet = diet


def _record_bedside_observations(stay: _Stay, run: _Run, day: int) -> None:
    """Vitals, on-demand PRN doses, the daily I/O record and ADL assessment."""
    patient, rng = stay.patient, stay.rng
    ward_nurse_id = assign_staff("medication_administration", stay.department, stay.roster, rng).get(
        "administering_nurse", FALLBACK_NURSE_ID
    )  # noqa: E501
    vitals_today = _generate_vitals(
        run.state,
        patient,
        day,
        stay.admission_time,
        rng,
        disease_id=stay.disease_id,
        nurse_id=ward_nurse_id,
        country=stay.country,
    )  # noqa: E501
    run.vitals.extend(vitals_today)
    # Issue #2085: PRN analgesia / benzodiazepines on demand from today's
    # pain scores and autonomic state.
    run.mars.extend(generate_prn_administrations(run.orders, vitals_today, run.state, run.prn_last_given))

    # Daily I/O record
    run.io_records.append(_generate_daily_io(run.state, patient, day, stay.admission_time, rng))

    # ADL assessment (admission, weekly, discharge approach)
    adl = _generate_adl_assessment(run.state, patient, day, stay.admission_time, rng)
    if adl:
        run.adl_assessments.append(adl)


def _apply_complications(stay: _Stay, run: _Run, day: int, comp_list: list) -> None:
    patient = stay.patient
    triggered = evaluate_complications(
        day,
        run.state,
        patient,
        comp_list,
        run.active_complications,
        stay.rng,
        severity=stay.severity,
        context=_complication_context(
            patient,
            run.orders,
            stay.admission_time,
            icu_day=run.icu_transferred_day if run.icu_transferred else None,
            intubated_day=run.intubated_day,
            surgery_day=stay.surgery[0] if stay.surgery else None,
            procedures=list(stay.prior_procedures or []) + run.escalation_procedures,
            dvt_prophylaxis=run.dvt_prophylaxis_planned,
        ),
    )
    for comp in triggered:
        for var, delta in comp.get("state_impact", {}).items():
            apply_state_delta(run.state, var, delta)
        comp_name = comp.get("name", "unknown")
        # Phase 1a: record the onset day + a canonical noon-of-day
        # timestamp so downstream (narrative context filter,
        # hospital_course_extractor ordering, future FHIR Condition
        # .onsetDateTime emit) knows WHEN the complication fired.
        # The daily loop is per-day, not per-hour, so noon is used
        # as a stable within-day anchor.
        onset_dt = stay.admission_time + timedelta(days=day)
        onset_dt = onset_dt.replace(hour=12, minute=0, second=0, microsecond=0)
        run.complications.append(
            build_complication(
                name=comp_name,
                onset_day=day,
                onset_datetime=onset_dt.isoformat(),
                source="daily_loop",
            )
        )
        if "icu_transfer" in comp.get("actions", []):
            if not run.icu_transferred:
                # C5-22: capture day of transfer for
                # Encounter.classHistory. First trigger wins;
                # subsequent ICU-triggering complications on later
                # days do not overwrite (the patient is already in
                # ICU by then).
                run.icu_transferred_day = day
            run.icu_transferred = True
        # Cancel contraindicated meds when AKI develops as complication
        if comp_name == "acute_kidney_injury":
            for o in run.orders:
                if o.order_type == OrderType.MEDICATION and o.status == OrderStatus.PLACED:
                    if has_drug([o], "metformin"):
                        o.status = OrderStatus.CANCELLED


def _escalate_airway_and_icu(stay: _Stay, run: _Run, day: int) -> None:
    """State-driven airway / ICU escalation (Issue #2091): intubation on the
    day the airway threshold is crossed, ICU transfer for airway or shock."""
    if not run.intubated and airway_escalation_needed(run.state):
        run.intubated = True
        run.intubated_day = day
        run.escalation_procedures.append(
            build_intubation_procedure(
                stay.patient.patient_id,
                stay.encounter_id,
                stay.admission_time + timedelta(days=day, hours=AIRWAY_ESCALATION_HOUR),
                stay.country,
                f"PROC-{stay.patient.patient_id}-AIR{day:02d}",
            )
        )
    if not run.icu_transferred and icu_escalation_needed(run.state):
        run.icu_transferred_day = day
        run.icu_transferred = True


def _dies_today(stay: _Stay, run: _Run, day: int, expected_mortality_multiplier: float) -> bool:
    """Mortality (disease-specific rate from YAML benchmarks)."""
    benchmark_mortality = stay.protocol.outcome_benchmarks.get(stay.country_key, {}).get("in_hospital_mortality", 0.0)
    return _evaluate_mortality(
        run.state,
        stay.patient,
        severity=stay.severity,
        day=day,
        rng=stay.rng,
        disease_mortality_rate=benchmark_mortality,
        target_los=stay.target_los,
        # Issue #2098: worst consciousness / oxygenation so far, relative to
        # the disease's presentation mix (keeps the benchmark average).
        state_relative_risk=mortality_state_multiplier(
            max(s.consciousness_impairment for s in run.state_history),
            max(s.oxygenation_impairment for s in run.state_history),
        )
        / expected_mortality_multiplier,
    )


def _gate_new_medication_orders(
    stay: _Stay, admission_orders: list[Order], orders: list[Order], admission_ids: set[str]
) -> list[Order]:
    """C7b (#1100): drug_safety gate on post-admission MEDICATION Orders.

    ``admission_orders`` were gated at admission time; anything the
    daily loop appended afterwards (treatment_mod step-up meds,
    complication-triggered add-ons) has never been checked. Partition
    ``orders`` into (admission, new) and route the new ones through
    the general gate, seeded with home + admission-accepted MEDICATION
    names so a mid-encounter Aspirin request against an admission-time
    Enoxaparin is skipped / substituted.
    """
    from clinosim.simulator.medication_pipeline import (
        apply_drug_safety_gate_to_orders,
    )

    # By id: an expanded admission panel order is replaced in place by its
    # components, which count as admission orders (Issue #2582).
    pre_new = [o for o in orders if o.order_id in admission_ids]
    new_orders = [o for o in orders if o.order_id not in admission_ids]
    if not new_orders:
        return orders
    accepted = [o.display_name for o in pre_new if o.order_type == OrderType.MEDICATION and o.display_name]
    gated_new = apply_drug_safety_gate_to_orders(
        new_orders,
        patient=stay.patient,
        encounter_id=admission_orders[0].encounter_id if admission_orders else "",
        ordered_datetime=stay.admission_time,
        attending_id=stay.attending_id,
        protocol=stay.protocol,
        country=stay.country_key,
        already_accepted_meds=accepted,
    )
    return pre_new + gated_new


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
) -> DailyLoopResult:
    """Run the day-by-day simulation loop. Returns all generated data.

    Each day runs the phases in a fixed order — state update, orders, lab
    results, diagnosis, archetype modifications, escalation, MAR, diet,
    bedside observations, complications, airway / ICU escalation — then the
    death / discharge / stay-extension checks. The order is load-bearing:
    the phases share one RNG stream.
    """
    stay = _Stay(
        patient=patient,
        disease_id=disease_id,
        protocol=protocol,
        archetype=archetype,
        admission_time=admission_time,
        target_los=target_los,
        healthcare=healthcare,
        roster=roster,
        rng=rng,
        chronic_monitoring=chronic_monitoring,
        country_key=country_key,
        min_los=min_los,
        hospital_state=hospital_state,
        hospital_ops=hospital_ops,
        attending_id=attending_id,
        department=department,
        severity=severity,
        encounter_id=encounter_id,
        # Thread imaging sequence counter from caller (initialized at day=0 in
        # simulate_inpatient_encounter). Fallback to {"I": 0} for callers that
        # don't pass it (backward-compat for direct test calls).
        imaging_seq=imaging_seq_counter if imaging_seq_counter is not None else {"I": 0},
        symptom_floor=symptom_floor,
        max_los=max_los,
        surgery=surgery,
        prior_procedures=prior_procedures,
    )
    run = _Run(
        state=state,
        differential=differential,
        orders=list(admission_orders),
        admission_order_ids={o.order_id for o in admission_orders},
        state_history=[deepcopy(state)],
        dvt_prophylaxis_planned=False,
    )
    expected_mortality_multiplier = expected_state_multiplier(protocol)
    run.dvt_prophylaxis_planned = _planned_dvt_prophylaxis(patient, protocol, admission_time, target_los)
    _escalate_on_arrival(stay, run)

    comp_list = protocol.complications if protocol.complications else []
    # The sampled target LOS is the stay ceiling; it is extended one day at a
    # time (up to max_los) while autonomic symptoms are uncontrolled. Stays
    # that never extend run exactly ``target_los`` days as before.
    los_ceiling = target_los
    actual_los = max(1, target_los)  # a stay whose loop never runs
    for day in range(max(target_los, max_los or 0)):
        actual_los = day + 1
        lab_state_pre_update = _advance_state(stay, run, day)
        if day >= 1:
            _place_daily_lab_and_imaging_orders(stay, run, day)
        # Chronic condition monitoring labs (additional to disease protocol)
        if chronic_monitoring and day >= 1:
            run.orders.extend(
                _place_chronic_monitoring_orders(
                    chronic_monitoring,
                    patient.patient_id,
                    day,
                    admission_time,
                    rng,
                    encounter_id=encounter_id,
                    ordered_by=attending_id,
                )
            )
        day_results_start = _result_labs(stay, run, day, lab_state_pre_update)
        if day >= 1:
            _update_diagnosis(stay, run, day, day_results_start)
        _apply_archetype_modifications(stay, run, day)
        if day == TREATMENT_ESCALATION_DAY and run.state.inflammation_level > TREATMENT_ESCALATION_INFLAMMATION_MIN:
            _escalate_treatment(stay, run, day)
        run.mars.extend(
            _generate_mar(patient, run.orders, day, admission_time, department=department, roster=roster, rng=rng)
        )
        _order_diet(stay, run, day)
        _record_bedside_observations(stay, run, day)
        if comp_list and day >= 1:
            _apply_complications(stay, run, day, comp_list)
        _escalate_airway_and_icu(stay, run, day)

        if _dies_today(stay, run, day, expected_mortality_multiplier):
            run.death_occurred = True
            break
        # Early discharge: if state-based criteria met before target_los
        # (not for protocols whose recovery the physiology does not model,
        # e.g. psychiatric admissions, Issue #2132).
        if day >= min_los and getattr(protocol, "state_based_discharge", True):
            if _check_discharge_ready(run.state, day, country_key, symptom_floor):
                break  # actual_los = day + 1
        if day + 1 >= los_ceiling:
            if not extend_stay_for_symptoms(run.state, los_ceiling, max_los, symptom_floor):
                break
            los_ceiling += 1

    return DailyLoopResult(
        orders=_gate_new_medication_orders(stay, admission_orders, run.orders, run.admission_order_ids),
        lab_results=run.lab_results,
        vitals=run.vitals,
        mars=run.mars,
        io_records=run.io_records,
        adl_assessments=run.adl_assessments,
        state_history=run.state_history,
        complications=run.complications,
        death_occurred=run.death_occurred,
        icu_transferred=run.icu_transferred,
        icu_transferred_day=run.icu_transferred_day,
        escalation_procedures=run.escalation_procedures,
        differential=run.differential,
        actual_los=actual_los,
    )


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

    lab_rules = lab_finding_rules()
    for r in lab_results:
        rule = lab_rules.get(r.lab_name)
        if rule is not None:
            v = r.value if isinstance(r.value, (int, float)) else 0
            findings.append((rule.finding, v > rule.above))

    # Day 1: imaging findings (simulated)
    if day == 1:
        findings.extend((finding, True) for finding in day1_imaging_findings(disease_id))

    return findings
