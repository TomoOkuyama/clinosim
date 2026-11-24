"""Per-day state machine extracted from `inpatient.py` (Issue #552 residual).

Contains the per-day loop that drives state update, orders, labs, MAR,
vitals, ADL/IO, complications, and discharge check for each simulated
day of an inpatient encounter. Extracted to reduce `inpatient.py`'s file
size ('s sibling-file convention: `lab_pipeline.py`,
`vitals_pipeline.py`, etc.).

Function bodies moved verbatim; byte-diff-neutral vs pre-extraction.
"""

from __future__ import annotations

import re
from copy import deepcopy
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta
from typing import Any

import numpy as np

from clinosim import determinism
from clinosim.codes.drugs import drug_classes, has_drug, protocol_drug_name, same_drug
from clinosim.countries import country_code
from clinosim.locale.free_text import localize_drug_name
from clinosim.locale.i18n import t
from clinosim.locale.loader import load_diet_type_display, narrative_label
from clinosim.locale.localized import language_slot, localized
from clinosim.modules._shared import MED_STOP_ORDER_ID_MARKER, sanitize_id_token
from clinosim.modules.clinical_course._complication_risk_conditions import ComplicationContext, in_drug_class
from clinosim.modules.clinical_course.engine import (
    apply_diagnosis_modifier,
    compute_diagnosis_effectiveness,
    evaluate_complications,
    get_daily_directive,
    natural_recovery_directive,
)
from clinosim.modules.code_status.engine import airway_declined
from clinosim.modules.diagnosis.engine import update_differential
from clinosim.modules.disease.localization import archetype_start_entries
from clinosim.modules.disease.protocol import DiseaseProtocol, load_disease_protocol
from clinosim.modules.drug_safety.hyperkalemia import (
    PotassiumHold,
    hyperkalemia_treatment_orders,
    potassium_history,
    potassium_hold_from_results,
)
from clinosim.modules.observation.engine import canonical_lab_name, lab_panel_components, medications_in_effect
from clinosim.modules.observation.fluid_balance_model import fluid_params, volume_status_shift
from clinosim.modules.observation.hemolysis_redraw import hemolysis_redraw_rules, is_hemolyzed
from clinosim.modules.observation.order_routing import lab_order_targets
from clinosim.modules.order.engine import (
    parse_dose_string,
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
from clinosim.seeding import adl_discharge_seed, complication_antibiotic_seed, vasopressor_start_seed
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
from clinosim.simulator.aki_response import (
    AkiCourse,
    LactateCourse,
    aki_course,
    date_aki_complications,
    discharge_extension_days,
    discharge_findings_unresolved,
    fever_persists,
    lactate_course,
)
from clinosim.simulator.complication_actions import (
    airway_actions_of,
    antibiotic_actions_of,
    complication_action_rules,
    first_line_antibiotics,
    regimen_protocol_id,
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
from clinosim.simulator.icu_step_down import day_has_icu_support, step_down_day
from clinosim.simulator.ketoacidosis_resolution import (
    basal_regimen_entry,
    ketoacidosis_resolution_rules,
    ketoacidosis_transition_due,
    stop_ketoacidosis_infusions,
)
from clinosim.simulator.lab_pipeline import _run_lab_result_pipeline, patient_true_labs
from clinosim.simulator.maintenance_iv_fluid import (
    maintenance_iv_fluid_rules,
    maintenance_iv_fluid_stopped,
    stop_maintenance_iv_fluid,
)
from clinosim.simulator.medication_pipeline import (
    ChildDosing,
    _generate_mar,
    _place_chronic_monitoring_orders,
    apply_vital_holds,
    child_dosing,
    dose_orders_for_child,
    generate_prn_administrations,
)
from clinosim.simulator.mixed_condition import CoDiseaseCourse
from clinosim.simulator.oral_intake import (
    apply_oral_intake_holds,
    first_npo_readings,
    npo_reason_at,
    oral_intake_rules,
)
from clinosim.simulator.oxygen_course import OxygenCourse, oxygen_course_rules
from clinosim.simulator.renal_antibiotic_dose import RenalDoseContext
from clinosim.simulator.vasoactive_support import (
    hospital_day_start,
    stop_weaned_vasoactive_infusions,
    vasoactive_infusion_during,
    vasoactive_support_after,
    vasoactive_weaning_rules,
)
from clinosim.simulator.vasopressor_initiation import (
    add_on_vasopressor_indicated,
    first_line_vasopressor,
    is_vasopressor_start,
    vasopressor_start_time,
)
from clinosim.simulator.ventricular_rate import VentricularRateCourse, first_rate_control_dose
from clinosim.simulator.vitals_pipeline import (
    _generate_adl_assessment,
    _generate_daily_io,
    _generate_vitals,
    lower_consciousness_from,
    oxygen_saturation_for_lab,
    put_on_niv,
    put_on_ventilator,
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


def in_shock(state: PhysiologicalState) -> bool:
    """Shock-level perfusion or distributive (septic) shock: vasopressor-level
    care (Issues #2110, #3270)."""
    return state.perfusion_status < ICU_SHOCK_PERFUSION_MAX or (
        state.inflammation_level >= ICU_DISTRIBUTIVE_SHOCK_INFLAMMATION
        and state.perfusion_status < ICU_DISTRIBUTIVE_SHOCK_PERFUSION_MAX
    )


def icu_escalation_needed(state: PhysiologicalState) -> bool:
    """Airway escalation, shock-level perfusion, distributive shock or a
    high-flow oxygen requirement: ICU care (Issues #2091, #2110)."""
    return (
        airway_escalation_needed(state) or in_shock(state) or state.oxygenation_impairment >= ICU_HIGH_FLOW_OXYGENATION
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
    # Issue #3270: a vasopressor / inotrope infusion ran within the observation
    # period before discharge (only when the stay reached its hard cap).
    on_vasoactive_support: bool = False
    # Issue #3281: the final creatinine meets the AKI definition.
    aki_at_discharge: bool = False
    # Issue #3637: the stay reached its extension cap still febrile.
    fever_at_discharge: bool = False
    # Issue #3539: the final lactate is at or above the metformin hold threshold.
    lactate_high_at_discharge: bool = False
    # Issue #3551: the patient decided against intubation, so the airway escalation
    # did not intubate (the code-status enricher assigns a tier that declines it).
    airway_declined: bool = False
    # Issue #3555: the hospital day (0-based) the patient moved back to the ward
    # from the ICU; None while in the ICU at discharge or death, or without a
    # transfer.
    icu_discharge_day: int | None = None


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
    # A minor's (age in months, weight at admission) for weight-based doses
    # (Issue #3004); None for an adult.
    child: ChildDosing | None = None
    # Issue #3392: the course of the co-disease of a mixed admission (None for a
    # stay with one disease).
    co_disease: CoDiseaseCourse | None = None
    # ED arrival of a via-ED admission (Issue #3434): the work-up is ordered in
    # the ED, so its first doses are given from the order, not from the
    # admission; None for a stay not admitted through the ED.
    ed_start: datetime | None = None
    # Issue #3633: the person's population-level death date when it falls on
    # or after the admission; the stay ends in death on that date.
    population_death_date: date | None = None

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
    icu_support: list[bool] = field(default_factory=list)  # Issue #3555: per hospital day, ICU-level support
    icu_trigger_days: set[int] = field(default_factory=set)  # Issue #3555: days an ICU-transfer complication began
    intubated: bool = False
    intubated_day: int | None = None  # Issue #2101: complication context
    airway_declined: bool = False  # Issue #3551: the airway threshold was crossed, the patient declined intubation
    escalation_procedures: list = field(default_factory=list)  # Issue #2091: state-driven intubation records
    prev_diet: str = ""  # last diet ordered for this patient
    oral_diet_since_day: int | None = None  # Issue #3409: day the diet first became oral (None: not oral)
    # Admission orders, including the components an admission panel order
    # was expanded into (Issue #2582); the drug-safety gate checks the rest.
    admission_order_ids: set[str] = field(default_factory=set)
    lab_time: datetime | None = None  # the most recent morning lab draw (none before day 1)
    potassium_hold: PotassiumHold | None = None  # Issue #2981: hyperkalemia hold, from the first K >= threshold
    hyperkalemia_last_day: int | None = None  # Issue #2981: last day with K >= threshold
    lactate: LactateCourse = field(default_factory=LactateCourse)  # Issue #3539: lactate course
    aki: AkiCourse = field(default_factory=AkiCourse)  # Issue #3281: creatinine course, KDIGO AKI per result
    oxygen: OxygenCourse = field(default_factory=OxygenCourse)  # Issue #3469: supplemental-oxygen state


def _airway_escalation_allowed(stay: _Stay, run: _Run) -> bool:
    """Issue #3551: the airway is secured only when the patient has not decided
    against intubation (a not-for-intubation or comfort-care status), decided
    before the escalation from a sub-RNG of the encounter id (no draw from the
    stay's RNG). The decision is kept on the run for the code-status enricher."""
    if run.airway_declined:
        return False
    if airway_declined(stay.patient.age, stay.country, stay.encounter_id):
        run.airway_declined = True
        return False
    return True


def _escalate_on_arrival(stay: _Stay, run: _Run) -> None:
    """Presentation already beyond the airway / ICU thresholds (e.g. GCS <= 8 on
    arrival): intubate and transfer on the admission day."""
    if airway_escalation_needed(run.state) and _airway_escalation_allowed(stay, run):
        run.intubated = True
        run.intubated_day = 0
        run.oxygen.start_ventilation(stay.admission_time + timedelta(hours=1))
        run.escalation_procedures.append(
            build_intubation_procedure(
                stay.patient.patient_id,
                stay.encounter_id,
                stay.admission_time + timedelta(hours=1),
                stay.country,
                f"PROC-{stay.patient.patient_id}-AIR00",
                performer_id=stay.attending_id,
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
    # Issue #3392: the treated co-disease of a mixed admission resolves.
    if stay.co_disease is not None:
        for var, delta in stay.co_disease.changes_on(day).items():
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
    # Issue #3649: a blood gas drawn on oxygen reflects the saturation on oxygen.
    sao2 = oxygen_saturation_for_lab(run.oxygen, lab_at, true_labs_state, stay.disease_id)
    true_labs = patient_true_labs(true_labs_state, patient, lab_at, flags, hour=lab_hour, sao2_pct=sao2)

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
    _redraw_hemolyzed(stay, run, day_results_start, true_labs, meds_in_effect)
    return day_results_start


def _redraw_hemolyzed(
    stay: _Stay,
    run: _Run,
    day_results_start: int,
    true_labs: dict[str, float],
    medications: list,
) -> None:
    """Issue #3452: a hemolyzed specimen of a redrawn analyte (potassium) is
    repeated. The repeat is a new stat lab order placed ``delay_minutes`` after
    the hemolyzed result and resulted from the true value by the same pipeline
    (own ``individual_lab_seed(order_id)`` stream, so no existing stream moves);
    a repeat that is hemolyzed or rejected too is repeated again, up to
    ``max_redraws``. Stays without a hemolyzed result are untouched."""
    rules = hemolysis_redraw_rules()
    by_result = {id(o.result): o for o in run.orders if o.result is not None}
    hemolyzed = [
        r
        for r in run.lab_results[day_results_start:]
        if r.lab_name in rules.labs and is_hemolyzed(r.flag) and id(r) in by_result
    ]
    n_existing = sum("-REDRAW-" in o.order_id for o in run.orders)
    for result in hemolyzed:
        source = by_result[id(result)]
        canon = result.lab_name
        at = result.result_datetime
        for _ in range(rules.max_redraws):
            n_existing += 1
            redraw = Order(
                order_id=f"ORD-{stay.encounter_id}-REDRAW-{n_existing:02d}",
                encounter_id=stay.encounter_id,
                patient_id=stay.patient.patient_id,
                order_type=OrderType.LAB,
                order_code=source.order_code,
                order_code_system=source.order_code_system,
                display_name=source.display_name,
                urgency="stat",
                clinical_intent=t("encounter_intent.hemolysis_redraw", "en", test=canon),
                clinical_intent_ja=t("encounter_intent.hemolysis_redraw", "ja", test=canon),
                ordered_datetime=(at + timedelta(minutes=rules.delay_minutes)).replace(second=0, microsecond=0),
                ordered_by=source.ordered_by,
                status=OrderStatus.PLACED,
            )
            run.orders.append(redraw)
            produced = _run_lab_result_pipeline(
                [redraw],
                {},
                set(),
                true_labs,
                stay.patient,
                stay.country_key,
                stay.roster,
                stay.hospital_state,
                stay.hospital_ops,
                medications=medications,
            )
            run.lab_results.extend(produced)
            if produced and not is_hemolyzed(produced[0].flag):
                break
            at = produced[0].result_datetime if produced else redraw.ordered_datetime


def _respond_to_hyperkalemia(stay: _Stay, run: _Run, day: int, day_results_start: int) -> None:
    """Issue #2981: a potassium result at or above the treatment threshold
    holds ACE inhibitors, ARBs and potassium-sparing diuretics for the rest of
    the stay and places the hyperkalemia order set (calcium, insulin, the
    dextrose given with it, a potassium binder) that day — only the binder
    again while the potassium stays high on consecutive days. Issue #3232:
    the hold carries every potassium resulted so far, so each dose is judged
    (digoxin) and explained by the latest one. No draws: a stay whose
    potassium stays below the threshold is unchanged."""
    today = potassium_hold_from_results(run.lab_results[day_results_start:])
    if run.potassium_hold is None and today is None:
        return
    history = potassium_history(run.lab_results)
    if run.potassium_hold is not None:
        run.potassium_hold = replace(run.potassium_hold, history=history)
    if today is None:
        return
    continuing = run.hyperkalemia_last_day == day - 1
    run.hyperkalemia_last_day = day
    if run.potassium_hold is None:
        run.potassium_hold = replace(today, history=history)
    run.orders.extend(
        hyperkalemia_treatment_orders(
            today,
            patient_id=stay.patient.patient_id,
            encounter_id=stay.encounter_id,
            country=stay.country_key,
            day=day,
            ordered_by=stay.attending_id,
            continuing=continuing,
            parse_dose=parse_dose_string,
        )
    )


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
    encounter_id = stay.encounter_id
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
                    clinical_intent=t(intent_key, "en", day=day),
                    # Issue #871: JA display for JP SR reasonCode.text.
                    clinical_intent_ja=t(intent_key, "ja", day=day),
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
                clinical_intent=t("order_intent.archetype_imaging", "en", day=day),
                # Issue #871: JA display for JP SR reasonCode.text.
                clinical_intent_ja=t("order_intent.archetype_imaging", "ja", day=day),
                ordered_datetime=ordered_at,
                status=OrderStatus.PLACED,
            )
        )


def _stop_archetype_medications(stay: _Stay, run: _Run, day: int, mod: dict) -> None:
    from clinosim.locale.free_text import localize_drug_name

    encounter_id = stay.encounter_id
    for stop_idx, drug_name in enumerate(mod.get("stop", [])):
        # Issue #3596: ``stop`` is not keyed by country, so it can name a drug
        # this stay never ordered (cefmetazole in a US stay); only a drug
        # actually running is stopped. No random draw.
        if _running_order(run.orders, drug_name) is None:
            continue
        run.orders.append(
            Order(
                order_id=(
                    f"ORD-{encounter_id}{MED_STOP_ORDER_ID_MARKER}D{day}-{stop_idx}-{sanitize_id_token(drug_name, 8)}"
                ),
                patient_id=stay.patient.patient_id,
                order_type=OrderType.MEDICATION,
                display_name=f"DISCONTINUE: {drug_name}",
                urgency="routine",
                clinical_intent=t("order_intent.archetype_stop", "en", day=day, drug=drug_name),
                # Issue #871: JA display for JP SR reasonCode.text.
                clinical_intent_ja=t(
                    "order_intent.archetype_stop", "ja", day=day, drug=localize_drug_name(drug_name, "ja")
                ),
                ordered_datetime=stay.admission_time + timedelta(days=day, hours=10),
                status=OrderStatus.PLACED,
            )
        )


def _running_order(orders: list[Order], drug: str) -> Order | None:
    """The latest order still giving ``drug`` (a catalog id or name), None
    when there is none: a later ``DISCONTINUE: <drug>`` marker stops it."""
    running: Order | None = None
    for order in orders:
        if order.order_type != OrderType.MEDICATION or order.status != OrderStatus.PLACED:
            continue
        name = order.display_name or ""
        if name.startswith("DISCONTINUE:"):
            if same_drug(name.removeprefix("DISCONTINUE:").strip(), drug):
                running = None
        elif same_drug(order.drug_id or name, drug):
            running = order
    return running


def _adjustment_of(running: Order | None) -> dict[str, Any]:
    """Order fields of a dose or rate change of ``running`` (Issue #3283):
    it replaces that order and keeps how the drug is given (route, dose,
    frequency, coding); the change itself is the order text
    ("Heparin increase_rate_by_20%"), never parsed as a dose."""
    if running is None:
        return {}
    return {
        "prior_order_id": running.order_id,
        "order_code": running.order_code,
        "order_code_system": running.order_code_system,
        "dose_quantity": running.dose_quantity,
        "dose_unit": running.dose_unit,
        "frequency": running.frequency,
        "frequency_per_day": running.frequency_per_day,
        "route": running.route,
        "drug_id": running.drug_id,
    }


def _start_archetype_treatments(stay: _Stay, run: _Run, day: int, mod: dict) -> None:
    """Start new medications or procedures.

    A medication entry with ``adjusts_active: true`` changes the dose or rate
    of the drug's running order (a heparin rate increase): the new order
    replaces that order (``prior_order_id``) and is given like it
    (:func:`_adjustment_of`), and the drug-safety gate does not check it
    against itself (Issue #3283).
    """
    encounter_id = stay.encounter_id
    day_time = stay.admission_time + timedelta(days=day, hours=10)
    for med in archetype_start_entries(mod, stay.country_key):
        if not isinstance(med, dict):
            continue
        # Issue #3332: a vasopressor starts from the recorded pressure
        # (``_start_vasopressor_for_hypotension``), not on this day; a second
        # one only while a vasopressor runs and the pressure stays low.
        if is_vasopressor_start(med) and (
            _running_drug(run.orders, str(med.get("drug_id") or protocol_drug_name(med)))
            or not add_on_vasopressor_indicated(run.orders, run.vitals, day_time)
        ):
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
            adjusted = (
                _adjustment_of(_running_order(run.orders, str(med.get("drug_id") or drug)))
                if order_type == OrderType.MEDICATION and med.get("adjusts_active") is True
                else {}
            )
            run.orders.append(
                Order(
                    order_id=order_id,
                    patient_id=stay.patient.patient_id,
                    order_type=order_type,
                    display_name=display,
                    urgency="urgent",
                    clinical_intent=t(intent_key, "en", day=day),
                    # Issue #871: JA display for JP SR reasonCode.text.
                    clinical_intent_ja=t(intent_key, "ja", day=day),
                    ordered_datetime=stay.admission_time + timedelta(days=day, hours=10),
                    status=OrderStatus.PLACED,
                    **adjusted,
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
                    clinical_intent=t("order_intent.archetype_procedure", "en", day=day),
                    # Issue #871: JA display for JP SR reasonCode.text.
                    clinical_intent_ja=t("order_intent.archetype_procedure", "ja", day=day),
                    ordered_datetime=stay.admission_time + timedelta(days=day, hours=10),
                    status=OrderStatus.PLACED,
                )
            )
        # Skip entries with neither drug nor procedure


def _running_drug(orders: list[Order], drug: str) -> bool:
    """Whether a placed order of ``drug`` (a drug id or name) exists."""
    return any(o.status == OrderStatus.PLACED and same_drug(o.drug_id or o.display_name, drug) for o in orders)


def _start_vasopressor_for_hypotension(stay: _Stay, run: _Run, day: int, vitals_today: list[VitalSignRecord]) -> None:
    """Start the protocol's first-line vasopressor when the day's recorded
    mean arterial pressure is low despite fluids (Issue #3332), and chart its
    doses of the rest of the day. The staff draw of those doses uses an own
    sub-RNG, so no draw of the stay's stream is added."""
    entry = first_line_vasopressor(stay.protocol, stay.archetype, stay.country_key)
    if entry is None:
        return
    start = vasopressor_start_time(run.orders, vitals_today, hospital_day_start(stay.admission_time, day))
    if start is None:
        return
    drug_name = protocol_drug_name(entry)
    dose = entry.get("dose", "")
    target = f"{vasoactive_weaning_rules().map_target_mmhg:g}"
    order = Order(
        order_id=f"ORD-{stay.encounter_id}-VASO-D{day}-{sanitize_id_token(drug_name, 8)}",
        encounter_id=stay.encounter_id,
        patient_id=stay.patient.patient_id,
        order_type=OrderType.MEDICATION,
        order_code=protocol_drug_order_code(entry, stay.country_key),
        order_code_system=protocol_drug_order_code_system(entry, stay.country_key),
        display_name=f"{drug_name} {dose}".strip(),
        urgency="urgent",
        clinical_intent=t("order_intent.vasopressor_for_hypotension", "en", day=day, target=target),
        clinical_intent_ja=t("order_intent.vasopressor_for_hypotension", "ja", day=day, target=target),
        ordered_datetime=start,
        ordered_by=stay.attending_id,
        status=OrderStatus.PLACED,
        route=entry.get("route", "IV"),
        dose_text_ja=language_slot(entry.get("dose_text"), "ja"),
        dose_text_en=language_slot(entry.get("dose_text"), "en"),
    )
    run.orders.append(order)
    run.mars.extend(
        _generate_mar(
            stay.patient,
            [order],
            day,
            stay.admission_time,
            department=stay.department,
            roster=stay.roster,
            rng=determinism.default_rng(vasopressor_start_seed(stay.encounter_id, day)),
            child=stay.child,
        )
    )


def _apply_antithrombotic_plan(stay: _Stay, run: _Run, day: int) -> None:
    """Start or stop the stay's antithrombotic agents of ``day`` (Issue #3277,
    ``simulator.antithrombotic_plan``): aspirin (plus clopidogrel for a minor
    stroke) for a patient without an anticoagulant indication; for one with
    it, aspirin until the anticoagulant starts. A new agent goes through the
    drug-safety gate at once, so a contraindicated one is skipped (logged)
    instead of given. Draws nothing."""
    if stay.protocol.antithrombotic_plan is None:
        return
    from clinosim.locale.free_text import localize_drug_name
    from clinosim.modules.order.engine import protocol_medication_orders
    from clinosim.simulator.antithrombotic_plan import steps_for_day
    from clinosim.simulator.medication_pipeline import apply_drug_safety_gate_to_orders

    steps = steps_for_day(
        stay.patient,
        stay.protocol,
        severity=stay.severity,
        country_key=stay.country_key,
        encounter_id=stay.encounter_id,
        day=day,
        is_running=lambda drug: _running_order(run.orders, drug) is not None,
        hemorrhage="hemorrhagic_transformation" in run.active_complications,
    )
    if not steps:
        return
    when = stay.admission_time + (timedelta(days=day, hours=10) if day else timedelta(hours=2))
    new_orders: list[Order] = []
    for idx, step in enumerate(steps):
        drug = protocol_drug_name(step.spec)
        if step.action == "stop":
            new_orders.append(
                Order(
                    order_id=(
                        f"ORD-{stay.encounter_id}{MED_STOP_ORDER_ID_MARKER}D{day}-AT{idx}-{sanitize_id_token(drug, 8)}"
                    ),
                    patient_id=stay.patient.patient_id,
                    order_type=OrderType.MEDICATION,
                    display_name=f"DISCONTINUE: {drug}",
                    urgency="routine",
                    clinical_intent=t("order_intent.archetype_stop", "en", day=day, drug=drug),
                    clinical_intent_ja=t(
                        "order_intent.archetype_stop", "ja", day=day, drug=localize_drug_name(drug, "ja")
                    ),
                    ordered_datetime=when,
                    status=OrderStatus.PLACED,
                )
            )
            continue
        new_orders.extend(
            protocol_medication_orders(
                step.spec,
                order_id=f"ORD-{stay.encounter_id}-ANTITHR-D{day}-{sanitize_id_token(drug, 8)}",
                encounter_id=stay.encounter_id,
                patient_id=stay.patient.patient_id,
                country=stay.country_key,
                ordered_datetime=when,
                ordered_by=stay.attending_id,
                urgency="urgent",
                order_set="",
            )
        )
    stops = [o for o in new_orders if (o.display_name or "").startswith("DISCONTINUE:")]
    starts = [o for o in new_orders if o not in stops]
    accepted = [
        o.display_name
        for o in run.orders
        if o.order_type == OrderType.MEDICATION
        and o.display_name
        and not o.display_name.startswith("DISCONTINUE:")
        and _running_order(run.orders, o.drug_id or o.display_name) is not None
    ]
    gated = apply_drug_safety_gate_to_orders(
        starts,
        patient=stay.patient,
        encounter_id=stay.encounter_id,
        ordered_datetime=when,
        attending_id=stay.attending_id,
        protocol=stay.protocol,
        country=stay.country_key,
        already_accepted_meds=[
            *(m.drug_name for m in stay.patient.current_medications or [] if m.drug_name),
            *accepted,
        ],
    )
    run.orders.extend([*stops, *gated])


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
        # Issue #3332: a vasopressor starts from the recorded pressure, not
        # on the escalation day.
        if is_vasopressor_start(esc_drug):
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
                clinical_intent_ja=t(
                    "order_intent.escalation",
                    "ja",
                    day=day,
                    drug=localize_drug_name(drug_name, "ja"),
                    # Issue #3107: the indication in clinical Japanese.
                    indication=narrative_label("escalation_indication", str(indication), "ja"),
                ),
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


def _append_diet_order(stay: _Stay, run: _Run, day: int, diet: str, when: datetime, suffix: str = "") -> None:
    """Place a diet order of ``diet`` at ``when`` unless it is the current diet."""
    if diet == run.prev_diet:
        return
    run.orders.append(
        Order(
            order_id=f"ORD-{stay.encounter_id}-DIET-D{day}{suffix}",
            patient_id=stay.patient.patient_id,
            order_type=OrderType.DIET,
            display_name=diet,
            urgency="routine",
            clinical_intent=t("order_intent.diet", "en", day=day, diet=diet),
            # Issue #871: JA display for JP SR reasonCode.text.
            # Issue #3107: the diet's Japanese name (diet_type_display).
            clinical_intent_ja=t(
                "order_intent.diet",
                "ja",
                day=day,
                diet=localized(load_diet_type_display().get(diet), "ja", fallback=diet),
            ),
            ordered_datetime=when,
            ordered_by=stay.attending_id,
            status=OrderStatus.PLACED,
        )
    )
    run.prev_diet = diet


def _order_diet(stay: _Stay, run: _Run, day: int) -> None:
    """Diet order (only when diet changes: NPO → clear liquid → soft → regular;
    the ventilated diet while the patient is on the ventilator, Issue #3535)."""
    order_time = stay.admission_time + timedelta(days=day, hours=7)
    if run.oxygen.ventilated_at(order_time):
        diet = oxygen_course_rules().ventilation.diet
    elif run.oxygen.niv_at(order_time):
        diet = oxygen_course_rules().niv.diet
    elif npo_reason_at(run.vitals, order_time, run.oxygen.ventilated_at, niv_at=run.oxygen.niv_at):
        # Issue #3552: the latest reading is P / U, the patient cannot swallow.
        diet = oral_intake_rules().npo_diet
    elif day == 0:
        diet = "NPO"
    elif day == 1 and run.state.inflammation_level > DIET_CLEAR_LIQUID_INFLAMMATION_THRESHOLD:
        diet = "clear_liquid"
    elif run.state.inflammation_level > DIET_SOFT_INFLAMMATION_THRESHOLD:
        diet = "soft_diet"
    else:
        diet = "regular_diet"
    _append_diet_order(stay, run, day, diet, order_time)
    # Issue #3409: the day the diet became oral starts the maintenance IV-fluid stop.
    if diet not in maintenance_iv_fluid_rules().oral_diets:
        run.oral_diet_since_day = None
    elif run.oral_diet_since_day is None:
        run.oral_diet_since_day = day


def _hold_oral_intake(stay: _Stay, run: _Run, day: int) -> None:
    """Issue #3552: at each reading of the day at a level that makes the
    patient nil by mouth (P / U) while the diet in force is oral, an NPO diet
    is ordered (a later day's diet order re-advances it once the level
    recovers), and every oral dose of the day scheduled while the patient is
    nil by mouth (P / U reading, ventilator) is held. Runs after the day's
    readings are final (complications, the airway escalation and the terminal
    course can change them). Draws nothing."""
    day_start = hospital_day_start(stay.admission_time, day)
    npo = oral_intake_rules().npo_diet
    diets = [o for o in run.orders if o.order_type == OrderType.DIET and o.status != OrderStatus.CANCELLED]
    for at in sorted(first_npo_readings(run.vitals, day_start)):
        in_force = max((o for o in diets if o.ordered_datetime <= at), key=lambda o: o.ordered_datetime, default=None)
        if in_force is not None and in_force.display_name == npo:
            continue
        run.prev_diet = in_force.display_name if in_force is not None else ""
        _append_diet_order(stay, run, day, npo, at, suffix=f"-LOC{at:%H%M}")
        diets = [o for o in run.orders if o.order_type == OrderType.DIET and o.status != OrderStatus.CANCELLED]
        run.oral_diet_since_day = None
    if diets:
        run.prev_diet = max(diets, key=lambda o: o.ordered_datetime).display_name
    day_end = day_start + timedelta(days=1)
    todays = [m for m in run.mars if day_start <= m.scheduled_datetime < day_end]
    apply_oral_intake_holds(todays, run.vitals, run.oxygen.ventilated_at, niv_at=run.oxygen.niv_at)


def _ventricular_rate_course(stay: _Stay, run: _Run) -> VentricularRateCourse | None:
    """The stay's ventricular-rate course when the protocol declares one
    (Issue #3274), from the first rate-control dose given so far (today's
    administrations are generated before today's vitals). Draws nothing."""
    spec = stay.protocol.ventricular_rate
    if spec is None:
        return None
    return VentricularRateCourse.build(
        spec, stay.severity, stay.archetype, stay.encounter_id, first_rate_control_dose(spec, run.mars)
    )


def _ventricular_rate_uncontrolled(stay: _Stay, run: _Run, day: int) -> bool:
    """True while the stay's ventricular rate at the end of ``day`` is at or
    above the protocol's ``discharge_below_bpm`` (Issue #3274); False for a
    protocol without a ventricular rate. Draws nothing."""
    course = _ventricular_rate_course(stay, run)
    if course is None or stay.protocol.ventricular_rate is None:
        return False
    end_of_day = stay.admission_time + timedelta(days=day + 1)
    return course.at(end_of_day) >= stay.protocol.ventricular_rate.discharge_below_bpm


def _loop_diuretic_given(mars: list[MedicationAdministration], day_date: Any) -> bool:
    """True when a loop diuretic dose was given on ``day_date``."""
    classes = set(fluid_params().loop_diuretic.drug_classes)
    for m in mars:
        if m.status != "given":
            continue
        when = m.actual_datetime or m.scheduled_datetime
        if when.date() == day_date and classes & set(drug_classes(m.drug_id)):
            return True
    return False


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
        ventricular_rate=_ventricular_rate_course(stay, run),
        oxygen=run.oxygen,
    )  # noqa: E501
    run.vitals.extend(vitals_today)
    _start_vasopressor_for_hypotension(stay, run, day, vitals_today)
    # Issue #2085: PRN analgesia / benzodiazepines on demand from today's
    # pain scores and autonomic state.
    run.mars.extend(generate_prn_administrations(run.orders, vitals_today, run.state, run.prn_last_given, run.aki))

    # Daily I/O record
    # Issue #3271: the day's intake / output follows the disease, the loop
    # diuretic given today and the physiological state, and its net balance
    # feeds back into volume_status (read from tomorrow's state).
    io_date = (stay.admission_time + timedelta(days=day)).date()
    io = _generate_daily_io(
        run.state,
        patient,
        day,
        stay.admission_time,
        rng,
        disease_id=stay.disease_id,
        on_loop_diuretic=_loop_diuretic_given(run.mars, io_date),
        maintenance_iv_stopped=maintenance_iv_fluid_stopped(run.orders, hospital_day_start(stay.admission_time, day)),
    )
    run.io_records.append(io)
    apply_state_delta(run.state, "volume_status", volume_status_shift(io.net_balance_ml, patient.weight_kg))

    # ADL assessment (admission, weekly, discharge approach)
    previous_adl = run.adl_assessments[-1].barthel_score if run.adl_assessments else None
    adl = _generate_adl_assessment(run.state, patient, day, stay.admission_time, rng, previous_score=previous_adl)
    if adl:
        run.adl_assessments.append(adl)


def _assess_adl_at_discharge(stay: _Stay, run: _Run, actual_los: int) -> None:
    """Issue #3647: an alive discharge has a Barthel assessment on the discharge
    date (admission date + ``actual_los``), from the final state. The noise comes
    from a per-encounter sha256 sub-seed, so the stay's stream is untouched;
    skipped when an assessment already exists that date."""
    adl = _generate_adl_assessment(
        run.state,
        stay.patient,
        actual_los,
        stay.admission_time,
        determinism.default_rng(adl_discharge_seed(stay.encounter_id)),
        previous_score=run.adl_assessments[-1].barthel_score if run.adl_assessments else None,
        at_discharge=True,
    )
    if adl is not None and all(a.date != adl.date for a in run.adl_assessments):
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
        # Issue #3540: the day's vitals were charted before this impact was
        # applied; the readings from the onset carry the lowered level.
        if comp.get("state_impact", {}).get("consciousness_impairment", 0.0) > 0:
            lower_consciousness_from(
                run.vitals, onset_dt, run.state, stay.disease_id, patient.patient_id, day, comp_name
            )
        for antibiotic_action in antibiotic_actions_of(comp):
            _start_complication_antibiotic(stay, run, day, comp_name, antibiotic_action, onset_dt)
        if oxygen_course_rules().niv.start_action in comp.get("actions", []):
            _start_niv(stay, run, day, onset_dt)
        # Issue #3639: a complication that requires intubation secures the airway
        # at its onset (the patient is then ventilated and in the ICU), unless
        # the patient is already intubated or has declined intubation.
        intubate = bool(airway_actions_of(comp))
        if intubate and not run.intubated and _airway_escalation_allowed(stay, run):
            _secure_airway(stay, run, day, onset_dt)
        if "icu_transfer" in comp.get("actions", []) or (intubate and run.intubated):
            run.icu_trigger_days.add(day)
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


def _start_complication_antibiotic(
    stay: _Stay, run: _Run, day: int, comp_name: str, action: str, onset_dt: datetime
) -> None:
    """Order the empirical antibiotic of an infectious complication on its
    onset day (Issue #3543) and chart its doses of the rest of the day.

    The regimen is the first-line antibiotic of the protocol the reference data
    names for the complication (``complication_actions``); it goes through the
    drug-safety gate (allergy, interaction, disease rules) like every daily-loop
    order. When the gate rules the whole first line out (a penicillin
    allergy), the protocol's own ``alternative_penicillin_allergy`` agent is
    ordered instead. Nothing is ordered when no regimen is named or the drug
    already runs. The staff draw of the doses uses an own sub-RNG, so no draw
    of the stay's stream is added."""
    from clinosim.modules.document.narrative.template_generator import _localize_complication
    from clinosim.modules.order.engine import protocol_medication_orders
    from clinosim.simulator.medication_pipeline import apply_drug_safety_gate_to_orders

    protocol_id = regimen_protocol_id(action, comp_name)
    if protocol_id is None:
        return
    drugs = load_disease_protocol(protocol_id).drugs
    when = onset_dt.replace(hour=complication_action_rules().order_hour)
    accepted = [
        o.display_name
        for o in run.orders
        if o.order_type == OrderType.MEDICATION
        and o.display_name
        and not o.display_name.startswith("DISCONTINUE:")
        and _running_order(run.orders, o.drug_id or o.display_name) is not None
    ]
    gated: list[Order] = []
    for block in ("first_line", "alternative_penicillin_allergy"):
        entries = first_line_antibiotics(drugs.get(block), stay.country_key)
        if any(_running_drug(run.orders, protocol_drug_name(e)) for e in entries):
            return
        candidates: list[Order] = []
        for idx, entry in enumerate(entries):
            for order in protocol_medication_orders(
                entry,
                order_id=f"ORD-{stay.encounter_id}-COMPABX-D{day}-{sanitize_id_token(comp_name, 12)}-{idx}",
                encounter_id=stay.encounter_id,
                patient_id=stay.patient.patient_id,
                country=stay.country_key,
                ordered_datetime=when,
                ordered_by=stay.attending_id,
                urgency="urgent",
                order_set="",
            ):
                complication = {lang: _localize_complication(comp_name, lang) or comp_name for lang in ("en", "ja")}
                order.clinical_intent = t(
                    "order_intent.complication_antibiotic", "en", day=day, complication=complication["en"]
                )
                order.clinical_intent_ja = t(
                    "order_intent.complication_antibiotic", "ja", day=day, complication=complication["ja"]
                )
                candidates.append(order)
        if not candidates:
            continue
        gated = apply_drug_safety_gate_to_orders(
            candidates,
            patient=stay.patient,
            encounter_id=stay.encounter_id,
            ordered_datetime=when,
            attending_id=stay.attending_id,
            protocol=stay.protocol,
            country=stay.country_key,
            already_accepted_meds=[
                *(m.drug_name for m in stay.patient.current_medications or [] if m.drug_name),
                *accepted,
            ],
        )
        if gated:
            break
    if not gated:
        return
    run.orders.extend(gated)
    run.mars.extend(
        _generate_mar(
            stay.patient,
            gated,
            day,
            stay.admission_time,
            department=stay.department,
            roster=stay.roster,
            rng=determinism.default_rng(complication_antibiotic_seed(stay.encounter_id, day, comp_name)),
            child=stay.child,
            renal=RenalDoseContext(run.lab_results, stay.country_key),
        )
    )


def _start_ventilation(stay: _Stay, run: _Run, day: int, intubated_at: datetime) -> None:
    """From the intubation the stay is ventilated (Issue #3535): the readings
    already charted today after the intubation time (the vitals were
    generated before the escalation) are rewritten as ventilator readings,
    later readings follow the oxygen course, and the diet becomes the
    ventilated diet from the intubation. Draws nothing."""
    run.oxygen.start_ventilation(intubated_at)
    put_on_ventilator(run.vitals, intubated_at, run.state, stay.disease_id)
    _append_diet_order(stay, run, day, oxygen_course_rules().ventilation.diet, intubated_at, suffix="-VENT")
    run.oral_diet_since_day = None


def _start_niv(stay: _Stay, run: _Run, day: int, started_at: datetime) -> None:
    """A complication that requires non-invasive ventilation (Issue #3705): from
    its onset the readings carry the NIV device, a NIV order is placed (it also
    gives the FHIR Procedure) and the diet is NPO while on NIV. Nothing happens
    when the patient is already ventilated or on NIV. Draws nothing."""
    if run.oxygen.ventilated_at(started_at) or run.oxygen.niv_at(started_at):
        return
    run.oxygen.start_niv(started_at)
    put_on_niv(run.vitals, started_at, run.state, stay.disease_id)
    niv = oxygen_course_rules().niv
    already_ordered = any(
        o.order_type == OrderType.PROCEDURE
        and o.status != OrderStatus.CANCELLED
        and re.search(niv.existing_order_pattern, o.display_name or "", re.IGNORECASE)
        for o in run.orders
    )
    if not already_ordered:
        run.orders.append(
            Order(
                order_id=f"ORD-{stay.encounter_id}-NIV-D{day}",
                patient_id=stay.patient.patient_id,
                order_type=OrderType.PROCEDURE,
                display_name=niv.order_name,
                urgency="urgent",
                clinical_intent=t("order_intent.niv", "en", day=day),
                clinical_intent_ja=t("order_intent.niv", "ja", day=day),
                ordered_datetime=started_at,
                ordered_by=stay.attending_id,
                status=OrderStatus.PLACED,
            )
        )
    # The day's diet order was placed before the complication (later in the day than its
    # onset): an oral diet ordered after NIV started is cancelled.
    cancelled = False
    for o in run.orders:
        if o.order_type == OrderType.DIET and o.ordered_datetime >= started_at and o.display_name != niv.diet:
            o.status = OrderStatus.CANCELLED
            cancelled = True
    if cancelled:
        kept = [o for o in run.orders if o.order_type == OrderType.DIET and o.status != OrderStatus.CANCELLED]
        run.prev_diet = max(kept, key=lambda o: o.ordered_datetime).display_name if kept else ""
    _append_diet_order(stay, run, day, niv.diet, started_at, suffix="-NIV")
    run.oral_diet_since_day = None


def _update_niv(stay: _Stay, run: _Run, day: int, *, last_day: bool) -> None:
    """End of day: wean NIV (at the start of the next hospital day) when the weaning
    rule of ``reference_data/oxygen_course.yaml`` is met. Draws nothing."""
    oxygen = run.oxygen
    if oxygen.niv_since is None or oxygen.niv_until is not None:
        return
    started_day = (oxygen.niv_since.date() - stay.admission_time.date()).days
    if oxygen.niv_wean_due(
        run.state.oxygenation_impairment,
        run.state.consciousness_impairment,
        day - started_day,
        force=last_day,
    ):
        oxygen.end_niv(hospital_day_start(stay.admission_time, day + 1))


def _update_ventilation(stay: _Stay, run: _Run, day: int, *, last_day: bool) -> None:
    """End of day: extubate (at the start of the next hospital day) when the
    extubation rule of ``reference_data/oxygen_course.yaml`` is met. Draws
    nothing."""
    oxygen = run.oxygen
    if oxygen.ventilated_since is None or oxygen.ventilated_until is not None or run.intubated_day is None:
        return
    if oxygen.extubation_due(
        run.state.oxygenation_impairment,
        run.state.consciousness_impairment,
        day - run.intubated_day,
        force=last_day,
    ):
        oxygen.end_ventilation(hospital_day_start(stay.admission_time, day + 1))


def _record_icu_support(stay: _Stay, run: _Run, day: int) -> None:
    """End of day: whether the day had ICU-level support (Issue #3555,
    ``reference_data/icu_step_down.yaml``), kept for the step-down derivation
    after the loop. Draws nothing."""
    start = hospital_day_start(stay.admission_time, day)
    today = [v for v in run.vitals if start <= v.timestamp < start + timedelta(days=1)]
    run.icu_support.append(
        day_has_icu_support(
            physiology_needs_icu=icu_escalation_needed(run.state),
            ventilated=run.oxygen.ventilated_during(start),
            vasoactive_infusion=vasoactive_infusion_during(run.orders, start, start + timedelta(days=1)),
            consciousness_levels=[v.consciousness_level for v in today],
            oxygen_flows_lpm=[v.oxygen_flow_rate_lpm for v in today if v.oxygen_flow_rate_lpm],
            icu_complication=day in run.icu_trigger_days,
        )
    )


def _secure_airway(stay: _Stay, run: _Run, day: int, intubated_at: datetime) -> None:
    """Intubate and ventilate from ``intubated_at``: the intubation procedure,
    the ventilator state of the readings from then on and the ventilated diet.
    The one path of the state-driven escalation and of a complication that
    requires intubation (Issue #3639). Draws nothing."""
    run.intubated = True
    run.intubated_day = day
    _start_ventilation(stay, run, day, intubated_at)
    run.escalation_procedures.append(
        build_intubation_procedure(
            stay.patient.patient_id,
            stay.encounter_id,
            intubated_at,
            stay.country,
            f"PROC-{stay.patient.patient_id}-AIR{day:02d}",
            performer_id=stay.attending_id,
        )
    )


def _escalate_airway_and_icu(stay: _Stay, run: _Run, day: int) -> None:
    """State-driven airway / ICU escalation (Issue #2091): intubation on the
    day the airway threshold is crossed, ICU transfer for airway or shock."""
    if not run.intubated and airway_escalation_needed(run.state) and _airway_escalation_allowed(stay, run):
        _secure_airway(stay, run, day, stay.admission_time + timedelta(days=day, hours=AIRWAY_ESCALATION_HOUR))
    if not run.icu_transferred and icu_escalation_needed(run.state):
        run.icu_transferred_day = day
        run.icu_transferred = True


def _dies_today(stay: _Stay, run: _Run, day: int, expected_mortality_multiplier: float) -> bool:
    """Mortality (disease-specific rate from YAML benchmarks)."""
    benchmark_mortality = stay.protocol.outcome_benchmarks.get(stay.country_key, {}).get("in_hospital_mortality", 0.0)
    drawn = _evaluate_mortality(
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
    # Issue #3633: the draw above is made either way (the stay's RNG stream is
    # unchanged); a person whose population death date is reached by the end of
    # today dies today, so the stay ends in that death, not in a discharge.
    return drawn or _population_death_due(stay, day)


def _population_death_due(stay: _Stay, day: int) -> bool:
    """True when the person's population death date is on or before the date
    the death would be recorded for a death today (Issue #3633). Draws nothing."""
    from clinosim.simulator.inpatient import _planned_discharge_datetime

    if stay.population_death_date is None:
        return False
    return _planned_discharge_datetime(stay.admission_time, day + 1, 0).date() >= stay.population_death_date


def _drop_doses_after_death(stay: _Stay, run: _Run, day: int) -> None:
    """No dose is charted after the death: the doses of the death day's
    hospital day (which runs 24 hours from the admission time) charted after
    the death time are removed, e.g. the rest-of-day doses of a vasopressor
    started for the terminal hypotension (Issue #3332). Draws nothing."""
    from clinosim.simulator.inpatient import _planned_discharge_datetime

    death_time = _planned_discharge_datetime(stay.admission_time, day + 1, 0)
    run.mars[:] = [m for m in run.mars if (m.actual_datetime or m.scheduled_datetime) <= death_time]


def _record_terminal_course(stay: _Stay, run: _Run, day: int) -> None:
    """Issue #2985: the final hours before a death drawn today deteriorate
    (``terminal_course.apply_terminal_course``). The death time is the one
    the inpatient simulator records (00:mm after the last hospital day)."""
    from clinosim.simulator.inpatient import _planned_discharge_datetime
    from clinosim.simulator.terminal_course import apply_terminal_course, drop_results_after_death

    death_time = _planned_discharge_datetime(stay.admission_time, day + 1, 0)
    # Issue #3280: no lab result is timed after the death.
    drop_results_after_death(run.orders, run.lab_results, death_time)
    apply_terminal_course(
        run.vitals,
        run.state_history,
        stay.patient,
        disease_id=stay.disease_id,
        encounter_id=stay.encounter_id,
        death_time=death_time,
        stay_oxygen=run.oxygen,
    )


def _wean_vasoactive_support(stay: _Stay, run: _Run, day: int) -> None:
    """Stop the running vasopressor / inotrope infusions at the start of the
    day once the pressures recorded before it met the target and the patient
    is out of shock (Issue #3270); no dose of them is given from then on.
    Draws nothing."""
    if day == 0:
        return
    stop_weaned_vasoactive_infusions(
        run.orders, run.mars, run.vitals, in_shock(run.state), hospital_day_start(stay.admission_time, day)
    )


def _transition_ketoacidosis_to_subcutaneous(stay: _Stay, run: _Run, day: int) -> None:
    """Switch a diabetic-ketoacidosis stay to subcutaneous basal insulin at the
    start of the day once the resulted labs meet the resolution criteria (or the
    infusion reached its day cap), and end the intravenous insulin, saline and
    potassium orders after the overlap (Issue #3450). Draws nothing."""
    if day == 0 or stay.disease_id not in ketoacidosis_resolution_rules().disease_ids:
        return
    day_start = hospital_day_start(stay.admission_time, day)
    if not ketoacidosis_transition_due(run.orders, run.lab_results, day_start):
        return
    from clinosim.modules.order.engine import protocol_medication_orders
    from clinosim.simulator.discharge_rx import _resolve_item_dose

    entry = basal_regimen_entry(stay.protocol.drugs or {}, stay.country_key)
    if entry is not None:
        patient = stay.patient
        home_meds = list(patient.baseline_chronic_medications or []) + list(patient.current_medications or [])

        def _weight() -> float:
            from clinosim.modules.population.encounter_anthropometry import encounter_weight_kg

            return float(encounter_weight_kg(patient, stay.encounter_id, stay.admission_time, stay.country_key))

        regimen = _resolve_item_dose(
            {**entry, "home_dose": "resume", "start_dose": {"rule": "basal_insulin"}}, home_meds, _weight
        )
        spec = {**entry, "dose": f"{regimen['dose']} {regimen['route']} {regimen['frequency']}".strip()}
        for order in protocol_medication_orders(
            spec,
            order_id=f"ORD-{stay.encounter_id}-DKA-SC-D{day}",
            encounter_id=stay.encounter_id,
            patient_id=patient.patient_id,
            country=stay.country,
            ordered_datetime=day_start,
            ordered_by=stay.attending_id,
            urgency="urgent",
            order_set="",
        ):
            order.drug_id = str(entry.get("drug_id") or "")
            order.clinical_intent = t("order_intent.ketoacidosis_sc_transition", "en", day=day)
            order.clinical_intent_ja = t("order_intent.ketoacidosis_sc_transition", "ja", day=day)
            run.orders.append(order)
    stop_ketoacidosis_infusions(run.orders, day_start)


def _on_vasoactive_support(stay: _Stay, run: _Run, day: int) -> bool:
    """Whether a vasopressor / inotrope infusion ran on any of the last
    ``off_support_days_before_discharge`` hospital days up to ``day``
    (Issue #3270)."""
    off_days = vasoactive_weaning_rules().off_support_days_before_discharge
    return vasoactive_support_after(run.orders, hospital_day_start(stay.admission_time, day + 1 - off_days))


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
    # Issue #3283: a rate change of an admission order follows its verdict,
    # and a re-order of an accepted drug is not checked against that drug.
    gated_new = apply_drug_safety_gate_to_orders(
        new_orders,
        patient=stay.patient,
        encounter_id=admission_orders[0].encounter_id if admission_orders else "",
        ordered_datetime=stay.admission_time,
        attending_id=stay.attending_id,
        protocol=stay.protocol,
        country=stay.country_key,
        already_accepted_meds=accepted,
        already_accepted_ids={o.order_id for o in pre_new if o.order_type == OrderType.MEDICATION},
        same_drug_reorder=True,
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
    *,
    country_key: str,
    min_los: int = 3,
    hospital_state: Any = None,
    hospital_ops: dict | None = None,
    attending_id: str = "",
    department: str = "internal_medicine",
    severity: str = "moderate",
    encounter_id: str = "",
    imaging_seq_counter: dict[str, int] | None = None,
    ed_start: datetime | None = None,
    symptom_floor: dict[str, float] | None = None,
    max_los: int | None = None,
    surgery: tuple[int, float] | None = None,
    prior_procedures: list | None = None,
    co_disease: CoDiseaseCourse | None = None,
    population_death_date: date | None = None,
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
        child=child_dosing(patient, encounter_id, admission_time, country_key),
        co_disease=co_disease,
        ed_start=ed_start,
        population_death_date=population_death_date,
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
    # time (up to max_los) while autonomic symptoms are uncontrolled, and up to
    # ``max_extension_days`` past max_los while on vasoactive support (Issue
    # #3270). Stays that never extend run exactly ``target_los`` days as before.
    los_ceiling = target_los
    actual_los = max(1, target_los)  # a stay whose loop never runs
    on_support = False
    unresolved = False
    loop_days = max(target_los, max_los or 0) + vasoactive_weaning_rules().max_extension_days
    for day in range(loop_days):
        actual_los = day + 1
        lab_state_pre_update = _advance_state(stay, run, day)
        if co_disease is not None:
            # Issue #3392: a late recognised co-disease is worked up and treated from today.
            run.orders.extend(co_disease.orders_due(day))
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
        _respond_to_hyperkalemia(stay, run, day, day_results_start)
        run.aki = aki_course(run.lab_results)
        run.lactate = lactate_course(run.lab_results)
        if day >= 1:
            _update_diagnosis(stay, run, day, day_results_start)
        _apply_archetype_modifications(stay, run, day)
        _apply_antithrombotic_plan(stay, run, day)
        if day == TREATMENT_ESCALATION_DAY and run.state.inflammation_level > TREATMENT_ESCALATION_INFLAMMATION_MIN:
            _escalate_treatment(stay, run, day)
        _wean_vasoactive_support(stay, run, day)
        _transition_ketoacidosis_to_subcutaneous(stay, run, day)
        # Issue #3409: the maintenance IV fluid ends once the patient eats.
        stop_maintenance_iv_fluid(
            run.orders, day, run.oral_diet_since_day, hospital_day_start(stay.admission_time, day)
        )
        mars_today = _generate_mar(
            patient,
            run.orders,
            day,
            admission_time,
            department=department,
            roster=roster,
            rng=rng,
            potassium_hold=run.potassium_hold,
            child=stay.child,
            aki=run.aki,
            lactate=run.lactate,
            dose_floor=stay.ed_start,
            renal=RenalDoseContext(run.lab_results, stay.country_key),
        )
        run.mars.extend(mars_today)
        _order_diet(stay, run, day)
        _record_bedside_observations(stay, run, day)
        # Issue #3233: the vital-sign hold parameters read the vital signs
        # recorded before each dose (today's are recorded after the MAR).
        apply_vital_holds(mars_today, run.vitals, patient.baseline_vitals, run.orders)
        if comp_list and day >= 1:
            _apply_complications(stay, run, day, comp_list)
        _escalate_airway_and_icu(stay, run, day)
        _hold_oral_intake(stay, run, day)

        if _dies_today(stay, run, day, expected_mortality_multiplier):
            run.death_occurred = True
            _record_terminal_course(stay, run, day)
            _hold_oral_intake(stay, run, day)
            # Issue #3332: the terminal hypotension is treated like any other.
            day_start = hospital_day_start(stay.admission_time, day)
            _start_vasopressor_for_hypotension(
                stay, run, day, [v for v in run.vitals if day_start <= v.timestamp < day_start + timedelta(days=1)]
            )
            _drop_doses_after_death(stay, run, day)
            break
        # Issue #3535: extubation at the start of tomorrow when the rule is
        # met; no discharge on a day the patient was ventilated.
        _record_icu_support(stay, run, day)
        _update_ventilation(stay, run, day, last_day=day + 1 >= loop_days)
        _update_niv(stay, run, day, last_day=day + 1 >= loop_days)
        day_start_dt = hospital_day_start(stay.admission_time, day)
        ventilated = run.oxygen.ventilated_during(day_start_dt) or run.oxygen.niv_during(day_start_dt)
        # Issue #3270: no discharge on or within the observation day after
        # vasopressor / inotrope support.
        on_support = _on_vasoactive_support(stay, run, day)
        # Issue #3274: an arrhythmia stay stays until its rate is controlled.
        rate_uncontrolled = _ventricular_rate_uncontrolled(stay, run, day)
        # Issue #3281: nor while AKI is not recovering or a fever persists.
        unresolved = discharge_findings_unresolved(run.aki, run.vitals)
        # Early discharge: if state-based criteria met before target_los
        # (not for protocols whose recovery the physiology does not model,
        # e.g. psychiatric admissions, Issue #2132).
        if (
            day >= min_los
            and getattr(protocol, "state_based_discharge", True)
            and not rate_uncontrolled
            and not ventilated
        ):
            if _check_discharge_ready(
                run.state,
                day,
                country_key,
                symptom_floor,
                on_vasoactive_support=on_support,
                findings_unresolved=unresolved,
            ):
                break  # actual_los = day + 1
        if day + 1 >= los_ceiling:
            if (
                not ventilated
                and not extend_stay_for_symptoms(
                    run.state, los_ceiling, max_los, symptom_floor, on_vasoactive_support=on_support
                )
                and not (rate_uncontrolled and max_los is not None and los_ceiling < max_los)
            ):
                # Issue #3281: one more day (at most ``max_extension_days``
                # past the sampled stay) while AKI is not recovering or a
                # fever persists.
                if not (unresolved and los_ceiling < target_los + discharge_extension_days(run.aki, run.vitals)):
                    break
            los_ceiling += 1

    # Issue #3642: the diagnosis is made from the creatinine, so the AKI is
    # dated at the first result that meets the definition.
    run.complications = date_aki_complications(run.complications, run.lab_results, stay.admission_time)
    if not run.death_occurred:
        # Issue #3450: the discharge day starts like any day, so a resolved
        # ketoacidosis goes home on subcutaneous insulin, not on the infusion.
        _transition_ketoacidosis_to_subcutaneous(stay, run, day + 1)
    if not run.death_occurred:
        _assess_adl_at_discharge(stay, run, actual_los)
    icu_discharge_day = None
    if run.icu_transferred:
        icu_discharge_day, _basis = step_down_day(
            run.icu_transferred_day, run.icu_support, actual_los, died=run.death_occurred
        )
    orders = _gate_new_medication_orders(stay, admission_orders, run.orders, run.admission_order_ids)
    # Orders placed after the last day's administrations (and substitutes of
    # the gate) are a minor's weight-based doses too (Issue #3004).
    dose_orders_for_child(orders, stay.child)
    return DailyLoopResult(
        orders=orders,
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
        icu_discharge_day=icu_discharge_day,
        escalation_procedures=run.escalation_procedures,
        differential=run.differential,
        actual_los=actual_los,
        on_vasoactive_support=on_support and not run.death_occurred,
        aki_at_discharge=run.aki.active and not run.death_occurred,
        fever_at_discharge=fever_persists(run.vitals) and not run.death_occurred,
        airway_declined=run.airway_declined,
        lactate_high_at_discharge=bool(run.lactate.points)
        and run.lactate.active_at(run.lactate.points[-1][0])
        and not run.death_occurred,
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
