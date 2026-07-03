"""Inpatient simulation — patient encounter, daily loop, MAR, vitals, etc."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta
from typing import Any

import numpy as np

from clinosim.modules.clinical_course.engine import (
    apply_diagnosis_modifier,
    compute_diagnosis_effectiveness,
    evaluate_complications,
    get_daily_directive,
    natural_recovery_directive,
    select_archetype,
)
from clinosim.modules.diagnosis.engine import (
    get_current_diagnosis_code,
    initialize_differential,
    update_differential,
)
from clinosim.modules.disease.protocol import DiseaseProtocol
from clinosim.modules.encounter.engine import create_inpatient_encounter
from clinosim.modules.observation.engine import (
    canonical_lab_name,
    determine_flag,
    generate_lab_result,
    get_lab_unit,
    lab_panel_components,
)
from clinosim.modules.order.engine import (
    calculate_result_time_from_state,
    place_admission_orders,
    place_daily_lab_orders,
    place_imaging_orders,
)
from clinosim.modules.physiology.engine import (
    apply_disease_onset,
    derive_lab_values,
    derive_observed_vitals,
    initialize_state,
    medication_flags_from_context,
    scenario_flags_from_protocol,
    update,
)
from clinosim.modules.population.engine import LifeEvent
from clinosim.modules.procedure.engine import (
    generate_bedside_procedures,
    generate_rehab_sessions,
    simulate_surgery,
)
from clinosim.modules.staff.engine import StaffRoster, assign_staff
from clinosim.types.clinical import (
    ClinicalDiagnosis,
    ConditionEvent,
    PhysiologicalState,
)
from clinosim.types.config import HealthcareSystemConfig, SimulatorConfig
from clinosim.types.encounter import (
    EncounterStatus,
    MedicationAdministration,
    Order,
    OrderResult,
    OrderStatus,
    OrderType,
    PrescriptionRecord,
    VitalSignRecord,
)
from clinosim.types.output import CIFPatientRecord
from clinosim.types.patient import PatientProfile

from clinosim.simulator.helpers import (
    _check_discharge_ready,
    _country_to_yaml_key,
    _determine_route,
    _disease_chief_complaint,
    _disease_to_department,
    _evaluate_mortality,
)
from clinosim.simulator.seeding import individual_lab_seed, panel_specimen_seed


# ============================================================
# Patient simulation
# ============================================================

def _simulate_patient(
    patient: PatientProfile,
    event: LifeEvent,
    disease_id: str,
    protocol: DiseaseProtocol,
    healthcare: HealthcareSystemConfig,
    roster: StaffRoster,
    config: SimulatorConfig,
    rng: np.random.Generator,
    forced_severity: str | None = None,
    forced_archetype: str | None = None,
    secondary_protocol: DiseaseProtocol | None = None,
    is_readmission: bool = False,
    prior_encounter_id: str | None = None,
    readmission_number: int = 0,
    hospital_state: Any = None,
    hospital_ops: dict | None = None,
) -> CIFPatientRecord:
    """Simulate one patient's complete hospital encounter.

    For mixed conditions, secondary_protocol provides the second disease's
    state impact and a secondary diagnosis to track.
    """

    # Severity & archetype (may be forced)
    if forced_severity:
        severity = forced_severity
    else:
        severity = "severe" if event.severity > 0.7 else ("moderate" if event.severity > 0.3 else "mild")
        # Apply minimum severity from protocol (e.g., fractures are at least moderate)
        if protocol.minimum_severity:
            severity_order = ["mild", "moderate", "severe"]
            min_idx = severity_order.index(protocol.minimum_severity) if protocol.minimum_severity in severity_order else 0
            cur_idx = severity_order.index(severity) if severity in severity_order else 0
            if cur_idx < min_idx:
                severity = protocol.minimum_severity

    if forced_archetype:
        archetype = forced_archetype
    else:
        archetype = select_archetype(severity, patient.physiological_profile, rng)

    # Initialize physiological state
    state = initialize_state(patient.physiological_profile, patient.chronic_conditions, patient.patient_id)

    # Readmission: carry over residual state from prior hospitalization
    if is_readmission:
        # Readmitted patients have worse baseline (incomplete recovery from prior stay)
        state.inflammation_level = max(state.inflammation_level, 0.05)
        state.renal_function = min(state.renal_function, 0.9)

    state = apply_disease_onset(state, severity, protocol.initial_state_impact,
                                acid_base_type=protocol.acid_base_type)

    # Scenario-implied chronic glycemic control (e.g. DKA/HHS imply long-standing poor
    # control). Overrides the patient's sampled glycemic_control so HbA1c is coherently high
    # even for new-onset diabetes. Persists through the stay (not an acute axis). AD-57.
    if protocol.chronic_glycemic_control is not None:
        state.glycemic_control = protocol.chronic_glycemic_control

    # Mixed condition: superimpose secondary disease's state impact
    secondary_disease_id = None
    if secondary_protocol:
        secondary_disease_id = secondary_protocol.disease_id
        # Secondary disease typically presents at moderate severity
        state = apply_disease_onset(state, "moderate", secondary_protocol.initial_state_impact,
                                    acid_base_type=secondary_protocol.acid_base_type)

    # Create encounter — realistic admission time pattern
    if protocol.encounter_type == "surgical":
        # Elective surgery: morning admission (8-10)
        adm_hour = int(rng.choice([8, 9, 10], p=[0.3, 0.5, 0.2]))
    elif event.severity > 0.6:
        # Emergency: any hour, peak in evening (ED presentation)
        adm_hour = int(rng.choice(24))
    else:
        # Urgent: daytime bias (9-20)
        adm_hour = int(rng.normal(14, 3))
        adm_hour = max(8, min(22, adm_hour))
    adm_minute = int(rng.integers(0, 60))
    admission_time = datetime(event.timestamp.year, event.timestamp.month, event.timestamp.day,
                               adm_hour, adm_minute)
    state.timestamp = admission_time
    chief_complaint = _disease_chief_complaint(protocol, country=config.country)
    encounter = create_inpatient_encounter(
        patient.patient_id, admission_time,
        chief_complaint=chief_complaint,
        visit_number=readmission_number + 1,
    )
    # β-JP-1 chain 1a (spec §2a): persist the selected severity + archetype on
    # the Encounter so Stage 2 narrative generation reads them from structural
    # CIF (they were previously in scope here but never written → every
    # narrative rendered severity-/archetype-agnostic).
    encounter.severity = severity
    encounter.clinical_course_archetype = archetype

    # Department resolution: granular YAML specialty → hospital's available department
    from clinosim.simulator.helpers import resolve_department, pick_ward
    granular_dept = _disease_to_department(protocol)
    department = resolve_department(granular_dept, hospital_ops)
    encounter.department_id = department
    staff = assign_staff("admission", department, roster, rng)
    attending_id = staff.get("attending_physician", "DR-001")
    encounter.attending_physician_id = attending_id

    # Ward assignment from hospital config
    encounter.ward_id = pick_ward(department, hospital_ops, rng)
    # Bed number from hospital ward_capacity (valid range for this ward)
    ward_cap = (hospital_ops or {}).get("ward_capacity", {}).get(encounter.ward_id, 10)
    bed_idx = int(rng.integers(1, ward_cap + 1))
    encounter.bed_number = f"{encounter.ward_id}-{bed_idx:02d}"

    # LOS (country-specific)
    country_key = _country_to_yaml_key(config.country)
    los_by_country = protocol.target_los.get(country_key) or protocol.target_los.get("japan", {})
    los_cfg = los_by_country.get(severity, {"mean": 14, "sd": 4, "min": 5, "max": 30})
    target_los = int(max(los_cfg.get("min", 5), min(los_cfg.get("max", 30), rng.normal(los_cfg["mean"], los_cfg["sd"]))))
    # Archetypes with treatment changes need minimum LOS to reach the change day
    if archetype in ("treatment_resistant", "plateau", "gradual_deterioration", "sudden_deterioration"):
        arc_data = (protocol.course_archetypes or {}).get(archetype, {})
        treatment_mods = arc_data.get("treatment_modifications", {})
        if treatment_mods:
            mod_days = [int(k.split("_")[1]) for k in treatment_mods if k.startswith("day_")]
            if mod_days:
                target_los = max(target_los, max(mod_days) + 2)

    # Admission orders
    admission_orders = place_admission_orders(
        protocol.model_dump(), patient.patient_id, encounter.encounter_id,
        admission_time, country=country_key, rng=rng, ordered_by=attending_id,
    )

    # Imaging orders from disease YAML imaging_orders[] (Tier 1 #2 PR1).
    # Counter is threaded across admission (day=0) + daily loop (day>=1) to
    # guarantee unique order_ids within the encounter.
    imaging_seq_counter: dict[str, int] = {"I": 0}
    adm_imaging = place_imaging_orders(
        protocol, encounter.encounter_id, patient.patient_id,
        admission_time, day_index=0, severity=severity, rng=rng,
        sequence_counter=imaging_seq_counter,
    )
    admission_orders.extend(adm_imaging)

    # Home medication orders (chronic condition continuation)
    home_med_orders, chronic_monitoring = _generate_home_medication_orders(
        patient, encounter.encounter_id, admission_time, attending_id, rng,
        state=state, disease_id=disease_id, protocol=protocol,
    )
    admission_orders.extend(home_med_orders)

    # Tracking
    procedures, rehab_sessions = [], []
    icu_transferred, death_occurred = False, False

    # Surgery (protocol-driven: requires_surgery flag in YAML)
    if protocol.requires_surgery:
        # Pick a surgeon and anesthesiologist from the roster
        surgeons = [m for m in roster.members if m.role == "physician"]
        surgeon_id = str(rng.choice(surgeons).staff_id) if surgeons else attending_id
        anes_id = str(rng.choice(surgeons).staff_id) if surgeons else attending_id
        operating_rooms = int(
            (hospital_ops or {}).get("resource_capacity", {}).get("operating_rooms", 2)
        )
        proc, impacts = simulate_surgery(patient, disease_id, encounter.encounter_id,
                                          admission_time, protocol, rng, config.country,
                                          surgeon_id=surgeon_id, anesthesiologist_id=anes_id,
                                          operating_rooms=operating_rooms)
        procedures.append(proc)
        for var, delta in impacts.items():
            cur = getattr(state, var, None)
            if cur is not None:
                setattr(state, var, max(-1.0, min(1.0, cur + delta)))
        rehab_sessions = generate_rehab_sessions(
            patient.patient_id, encounter.encounter_id,
            proc.start_datetime, target_los, rng, config.country,
        )

    # Bedside / routine procedures (disease-driven rules)
    bedside = generate_bedside_procedures(
        patient.patient_id, encounter.encounter_id, disease_id,
        admission_time, severity, rng, config.country,
    )
    procedures.extend(bedside)

    # Apply state impacts from bedside procedures (e.g., blood transfusion)
    for proc in bedside:
        if proc.procedure_type == "blood_transfusion":
            # Each unit of RBC raises Hgb ~1 g/dL → anemia_level -0.07 per unit
            # Assume 1-2 units per transfusion event
            state.anemia_level = max(0.0, state.anemia_level - 0.15)
            state.volume_status = min(1.0, state.volume_status + 0.05)

    # Differential diagnosis
    protocol_diagnostic = protocol.diagnostic if hasattr(protocol, 'diagnostic') else {}
    differential = initialize_differential(disease_id, patient.age, protocol_diagnostic=protocol_diagnostic)

    # Daily simulation loop
    has_diabetes = any(c.code.startswith("E11") for c in patient.chronic_conditions)
    protocol_min_los = los_cfg.get("min", 3)
    loop_result = _run_daily_loop(
        state, patient, disease_id, protocol, archetype, differential,
        admission_orders, admission_time, target_los, has_diabetes,
        healthcare, roster, rng,
        chronic_monitoring=chronic_monitoring,
        country_key=country_key,
        min_los=protocol_min_los,
        hospital_state=hospital_state,
        hospital_ops=hospital_ops,
        attending_id=attending_id,
        encounter_id=encounter.encounter_id,
        department=department,
        severity=severity,
        imaging_seq_counter=imaging_seq_counter,
    )

    # Unpack results
    all_orders = loop_result["orders"]
    all_lab_results = loop_result["lab_results"]
    all_vitals = loop_result["vitals"]
    all_mars = loop_result["mars"]
    all_io = loop_result.get("io_records", [])
    all_adl = loop_result.get("adl_assessments", [])
    state_history = loop_result["state_history"]
    complications_occurred = loop_result["complications"]
    death_occurred = loop_result["death_occurred"]
    icu_transferred = loop_result["icu_transferred"]
    differential = loop_result["differential"]
    actual_los = loop_result["actual_los"]

    # Final diagnosis
    protocol_diagnostic = protocol.diagnostic if hasattr(protocol, 'diagnostic') else {}
    yaml_progression = protocol_diagnostic.get("diagnosis_progression") if protocol_diagnostic else None
    dx_code, dx_name = get_current_diagnosis_code(differential, protocol_progression=yaml_progression)

    # Diagnosis correctness and missed diagnoses (AD-29)
    missed: list[str] = []
    overcalled: list[str] = []
    if secondary_protocol and secondary_disease_id:
        # 30% chance of missing the secondary diagnosis in mixed cases
        if rng.random() < 0.30:
            missed.append(secondary_disease_id)

    icd_sys = "icd-10" if country_key == "japan" else "icd-10-cm"
    clinical_diagnosis = ClinicalDiagnosis(
        admission_diagnosis_code=protocol.icd_codes.get("primary", ""),
        admission_diagnosis_system=icd_sys,
        discharge_diagnosis_code=dx_code,
        discharge_diagnosis_system=icd_sys,
        diagnosis_correct=(dx_code != "R05" and not missed),
        missed_diagnoses=missed,
        overcalled_diagnoses=overcalled,
    )

    # Build ground truth diseases list
    if event.condition_type == "mixed" and secondary_disease_id:
        gt_diseases = [disease_id, secondary_disease_id]
    elif event.condition_type == "known_disease":
        gt_diseases = [disease_id]
    else:
        gt_diseases = [disease_id]

    condition_event = ConditionEvent(
        condition_id=f"COND-{patient.patient_id}-001",
        condition_type=event.condition_type,
        ground_truth_diseases=gt_diseases,
    )

    # Discharge prescription
    final_renal = state.renal_function if state else 1.0
    discharge_rx = _build_discharge_rx(
        patient, disease_id, protocol, attending_id, admission_time, rng,
        country_key=country_key, final_renal_function=final_renal,
    ) if not death_occurred else None

    # Enrich medication orders with parsed dose/frequency/route
    from clinosim.modules.order.engine import enrich_medication_order
    for o in all_orders:
        if o.order_type == OrderType.MEDICATION:
            enrich_medication_order(o)
        # Set encounter_id for all orders that don't have one
        if not o.encounter_id:
            o.encounter_id = encounter.encounter_id

    # Set encounter discharge fields
    encounter.discharging_physician_id = attending_id
    encounter.admitting_physician_id = attending_id
    if not encounter.admit_source:
        encounter.admit_source = "emd"  # Most inpatients come via ED
    if not encounter.discharge_disposition:
        if death_occurred:
            encounter.discharge_disposition = "expired"
        else:
            encounter.discharge_disposition = "home"
    if not encounter.priority:
        encounter.priority = "EM" if disease_id in ("acute_mi", "sepsis", "hemorrhagic_stroke",
                                                     "subdural_hematoma", "traffic_accident_severe") else "UR"

    # Discharge time: morning (10-12) for planned discharge, any time for death
    dc_hour = 0 if death_occurred else int(rng.normal(11, 1.5))
    dc_hour = max(9, min(16, dc_hour)) if not death_occurred else 0
    planned_discharge = admission_time + timedelta(days=actual_los, hours=dc_hour)

    # Snapshot truncation: if planned discharge is after snapshot date,
    # patient is still admitted as of snapshot → no discharge_datetime
    snapshot_dt = None
    if config.snapshot_date:
        snapshot_dt = datetime.strptime(config.snapshot_date, "%Y-%m-%d").replace(
            hour=23, minute=59, second=59,
        )

    if snapshot_dt and planned_discharge > snapshot_dt and not death_occurred:
        # Truncate: patient is currently admitted
        encounter.status = EncounterStatus.IN_PROGRESS
        encounter.discharge_datetime = None
        encounter.discharge_disposition = ""  # not yet discharged
        encounter.discharging_physician_id = ""
        # Drop data generated after the snapshot date
        all_orders = [o for o in all_orders if o.ordered_datetime <= snapshot_dt]
        all_vitals = [v for v in all_vitals if v.timestamp <= snapshot_dt]
        all_lab_results = [r for r in all_lab_results if r.result_datetime <= snapshot_dt]
        all_mars = [m for m in all_mars
                    if (m.actual_datetime or m.scheduled_datetime) <= snapshot_dt]
        # Discharge prescription not yet issued
        discharge_rx = None
    else:
        encounter.status = EncounterStatus.COMPLETED
        encounter.discharge_datetime = planned_discharge

    # Microbiology cultures + susceptibilities (AD-55 Base) — infections only.
    # Encounter-scoped sub-seed keeps the main random stream unperturbed (AD-16).
    from clinosim.modules.observation.microbiology import generate_microbiology, has_microbiology
    microbiology: list = []
    if has_microbiology(disease_id):
        microbiology = generate_microbiology(
            disease_id, admission_time, encounter.encounter_id, config.random_seed,
        )
        if snapshot_dt:  # drop cultures not yet resulted as of snapshot
            microbiology = [
                m for m in microbiology
                if m.reported_datetime is None or m.reported_datetime <= snapshot_dt
            ]

    record = CIFPatientRecord(
        patient=patient, encounters=[encounter], orders=all_orders,
        vital_signs=all_vitals, lab_results=all_lab_results,
        condition_event=condition_event, clinical_diagnosis=clinical_diagnosis,
        complications_occurred=complications_occurred,
        procedures=procedures, rehab_sessions=rehab_sessions,
        medication_administrations=all_mars,
        intake_output_records=all_io,
        adl_assessments=all_adl,
        microbiology=microbiology,
        discharge_prescription=discharge_rx,
        icu_transferred=icu_transferred, deceased=death_occurred,
        death_day=actual_los if death_occurred else None,
        is_readmission=is_readmission,
        prior_encounter_id=prior_encounter_id,
        readmission_number=readmission_number,
        physiological_states=state_history,
    )

    # POST_ENCOUNTER stage (AD-55 encounter-bound Modules) — runs after
    # the daily loop produces the full clinical course. Currently:
    #   - modules/device places CVC / catheter / ventilator based on
    #     record.icu_transferred + per-day state (which is now available).
    #   - modules/hai samples CLABSI / CAUTI / VAP onsets from device
    #     line-days (CDC NHSN baseline), appends MicrobiologyResult for
    #     culture, and writes list[HAIEvent] under extensions["hai"].
    #   - modules/imaging derives ImagingStudyRecord (FHIR) from Order(IMAGING)
    #     and writes list[ImagingStudyRecord] under extensions["imaging"].
    # Per-patient sub-seed via ENRICHER_SEED_OFFSETS so the main RNG is
    # untouched (AD-16).
    from clinosim.simulator.enrichers import (
        POST_ENCOUNTER,
        EnricherContext,
        run_stage,
    )

    # Store disease_id in extensions for enrichers that need it (e.g. imaging
    # enricher for impression template selection). Modules read via:
    #   disease_id = (record.extensions or {}).get("_disease_id", "")
    # Transient IPC key for inpatient simulator → enricher communication; cleaned up at
    # end of enricher run (e.g. imaging_enricher); NOT included in FHIR output (AD-30).
    if not record.extensions:
        record.extensions = {}
    record.extensions["_disease_id"] = disease_id

    run_stage(
        POST_ENCOUNTER,
        EnricherContext(
            config=config,
            master_seed=config.random_seed,
            records=[record],
            roster=roster,  # nursing_enricher (order=94) samples primary_nurse_id from roster
        ),
    )

    # Cleanup transient IPC key _disease_id (I-6 fix, 2026-06-30). Moved here
    # from imaging_enricher so cleanup is exception-safe (fires even if enricher
    # raises mid-loop) and future POST_ENCOUNTER enrichers at order > 90 can
    # still read _disease_id during run_stage. Underscore prefix signals transient
    # IPC key; must NOT leak into FHIR output (AD-30).
    if record.extensions:
        record.extensions.pop("_disease_id", None)

    # AD-32 snapshot truncation for encounter-bound Modules. The earlier
    # filter (lines 386-390) ran BEFORE POST_ENCOUNTER, so device + HAI
    # outputs need their own snapshot pass: drop HAI events whose onset_date
    # is past the snapshot (the patient hasn't acquired it yet as of the
    # snapshot date), drop HAI cultures whose reported_datetime is past the
    # snapshot, and re-run the microbiology truncation to catch HAI-appended
    # cultures the pre-POST_ENCOUNTER filter missed.
    if snapshot_dt is not None:
        from datetime import date as _date
        snapshot_date = snapshot_dt.date()
        ext = record.extensions or {}
        ext_hai = ext.get("hai") or []
        if ext_hai:
            kept_hai = []
            for ev in ext_hai:
                onset_str = getattr(ev, "onset_date", None) or ""
                try:
                    onset = _date.fromisoformat(onset_str)
                except (TypeError, ValueError):
                    kept_hai.append(ev)
                    continue
                if onset > snapshot_date:
                    continue
                kept_hai.append(ev)
            if len(kept_hai) != len(ext_hai):
                ext["hai"] = kept_hai
        if record.microbiology:
            record.microbiology = [
                m for m in record.microbiology
                if m.reported_datetime is None or m.reported_datetime <= snapshot_dt
            ]

    # Phase 3a (2026-06-25): apply HAI WBC + CRP forward-delta lift to
    # existing lab_results for any encounter day on/after each HAI
    # event's onset_date. Uses the per-day state_history to compute the
    # delta from derive_lab_values' hai_inflammation_lift kwarg so the
    # original noise + circadian on the observation values is preserved.
    from clinosim.modules.hai.lab_lift import apply_hai_lab_lift

    apply_hai_lab_lift(
        record=record,
        encounter=encounter,
        state_history=state_history,
        admission_time=admission_time,
    )

    return record


# ============================================================
# Daily simulation loop
# ============================================================

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
    healthcare: HealthcareSystemConfig,
    roster: StaffRoster,
    rng: np.random.Generator,
    chronic_monitoring: list[dict] | None = None,
    country_key: str = "japan",
    min_los: int = 3,
    hospital_state: Any = None,
    hospital_ops: dict | None = None,
    attending_id: str = "",
    department: str = "internal_medicine",
    severity: str = "moderate",
    encounter_id: str = "",
    imaging_seq_counter: dict[str, int] | None = None,
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
    all_io: list = []
    all_adl: list = []
    state_history = [deepcopy(state)]
    active_complications: set[str] = set()
    complications_occurred: list[str] = []
    death_occurred = False
    icu_transferred = False

    # Determine severity string for natural recovery scaling
    severity_str = "moderate"  # default
    for s in ("severe", "moderate", "mild"):
        los_data = (protocol.target_los.get(country_key) or {}).get(s)
        if los_data and abs(target_los - los_data.get("mean", 14)) < 5:
            severity_str = s
            break

    prev_diet = ""  # last diet ordered for this patient; threaded through the day loop
    for day in range(target_los):
        # State update with diagnosis-treatment feedback
        directive = get_daily_directive(
            archetype, day, patient.physiological_profile,
            protocol_archetypes=protocol.course_archetypes or None,
            age=patient.age, rng=rng,
        )

        # Phase 1: Dampen recovery if diagnosis is wrong
        dx_confidence = 0.0
        working_dx = None
        if differential.top_candidate:
            dx_confidence = differential.top_candidate.probability
            working_dx = differential.top_candidate.disease_code
        dx_difficulty = (protocol.diagnostic or {}).get("diagnostic_difficulty", 0.3)
        effectiveness = compute_diagnosis_effectiveness(
            working_dx, disease_id, dx_confidence, day,
            diagnostic_difficulty=dx_difficulty,
        )
        directive = apply_diagnosis_modifier(
            directive, effectiveness,
            current_volume=state.volume_status,
            current_ph=state.ph_status,
        )

        # Phase 2: Natural recovery (small baseline healing)
        nat_directive = natural_recovery_directive(
            day, disease_id, severity_str, patient.physiological_profile,
        )
        for var, delta in nat_directive.changes.items():
            directive.changes[var] = directive.changes.get(var, 0.0) + delta

        state = update(state, directive, timedelta(days=1))
        state_history.append(deepcopy(state))

        # Daily lab orders (from Day 1) with context-dependent frequency
        if day >= 1:
            # Morning lab draw: 05:30-07:00 with jitter
            lab_hour = 6
            lab_min = int(rng.integers(0, 45))  # 06:00-06:45
            if rng.random() < 0.2:
                lab_hour = 5
                lab_min = int(rng.integers(30, 60))  # 05:30-06:00
            lab_time = datetime(
                admission_time.year, admission_time.month, admission_time.day,
                lab_hour, lab_min,
            ) + timedelta(days=day)

            # Context-dependent lab frequency modulation
            freq_mod = healthcare.lab_frequency_multiplier
            # Severity: severe patients get more frequent labs, mild get fewer
            severity_mult = {"severe": 1.3, "moderate": 1.0, "mild": 0.6}.get(severity, 1.0)
            freq_mod *= severity_mult
            # Near discharge: reduce routine labs
            if day >= target_los - 2 and state.inflammation_level < 0.1:
                freq_mod *= 0.5
            # Weekend: reduce non-urgent labs
            if lab_time.weekday() >= 5:  # Saturday/Sunday
                freq_mod *= 0.7
            # Stable patient: reduce after first week
            if day >= 7 and state.inflammation_level < 0.15:
                freq_mod *= 0.8

            daily_orders = place_daily_lab_orders(
                protocol.model_dump(), patient.patient_id, encounter_id, day, lab_time,
                freq_mod, rng, ordered_by=attending_id,
            )
            all_orders.extend(daily_orders)

            # Imaging orders for day >= 1 (day=0 handled pre-loop in
            # simulate_inpatient_encounter). Counter threads from admission
            # call so IDs are unique across the full encounter.
            daily_imaging = place_imaging_orders(
                protocol, encounter_id, patient.patient_id,
                admission_time, day_index=day, severity=severity, rng=rng,
                sequence_counter=_img_seq,
            )
            all_orders.extend(daily_imaging)

        # Chronic condition monitoring labs (additional to disease protocol)
        if chronic_monitoring and day >= 1:
            chronic_lab_orders = _place_chronic_monitoring_orders(
                chronic_monitoring, patient.patient_id, day, admission_time, rng,
                encounter_id=encounter_id, ordered_by=attending_id,
            )
            all_orders.extend(chronic_lab_orders)

        # Lab results (with temporal lag for slow markers like CRP)
        lab_hour = lab_time.hour if 'lab_time' in dir() else 6  # early morning default
        # J5 (Phase 2a): read every scenario flag (causes_myocardial_injury,
        # causes_vte, future additions) via one helper and splat with **flags
        # so every call site stays in sync. See physiology.engine docstring.
        # Phase 2b (2026-06-24): sibling helper medication_flags_from_context
        # detects chronic warfarin from current_medications AND in-hospital
        # warfarin orders >= 3 days old (loading-dose 3-day rule). Both
        # helpers spread as **flags so a new flag added to derive_lab_values
        # reaches this site without touching the call.
        _med_orders = [o for o in all_orders if o.order_type.value == "medication"]
        flags = {
            **scenario_flags_from_protocol(protocol),
            **medication_flags_from_context(
                patient,
                medication_orders=_med_orders,
                admission_date=admission_time.date(),
                current_day=day,
            ),
        }
        true_labs = derive_lab_values(state, sex=patient.sex, age=patient.age, has_diabetes=has_diabetes, hour=lab_hour, **flags)

        # Apply temporal lag: CRP reflects inflammation from ~1 day ago
        if len(state_history) >= 2 and "CRP" in true_labs:
            lag_idx = max(0, len(state_history) - 2)
            lagged_state = state_history[lag_idx]
            lagged_labs = derive_lab_values(lagged_state, sex=patient.sex, age=patient.age, has_diabetes=has_diabetes, hour=lab_hour, **flags)
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
                for comp in comps:
                    children.append(Order(
                        order_id=f"{order.order_id}-{comp}", patient_id=order.patient_id,
                        order_type=OrderType.LAB, display_name=comp, urgency=order.urgency,
                        clinical_intent=order.clinical_intent,
                        ordered_datetime=order.ordered_datetime, ordered_by=order.ordered_by,
                        encounter_id=order.encounter_id, status=OrderStatus.PLACED,
                    ))
                _panel_children_by_parent[order.order_id] = children
                order.status = OrderStatus.RESULTED

        # The flat list (preserves insertion order so downstream serialisers, e.g.
        # _bb_labs in fhir_r4_adapter, retain a stable index for `lab-{enc}-{idx:04d}`).
        _panel_children: list[Order] = [
            c for kids in _panel_children_by_parent.values() for c in kids
        ]
        all_orders.extend(_panel_children)
        _panel_child_ids = {c.order_id for c in _panel_children}

        # === Pass 1: scalar + non-panel orders, drawn from a per-order isolated
        # sub-RNG (individual_lab_seed). This mirrors the panel-children Pass 2
        # design: each individual lab order is one specimen, so specimen
        # rejection, hemolysis, technician assignment, and noise must come from
        # an isolated stream so YAML edits that flip a {test:"X"} order from
        # "engine doesn't produce X" to "engine produces X" (e.g. Cl/Ca after
        # derive_lab_values is extended) cannot shuffle unrelated patients'
        # cohorts via the master stream (AD-16). Panel children are skipped
        # here; they are resulted in Pass 2 against panel_specimen_seed.
        for order in all_orders:
            if order.order_id in _panel_child_ids:
                continue
            canon = canonical_lab_name(order.display_name)
            if order.order_type.value == "lab" and order.status == OrderStatus.PLACED and canon in true_labs:
                lab_rng = np.random.default_rng(individual_lab_seed(order.order_id))
                # Pre-analytical issues: specimen rejection (~2%), hemolysis (~3% for K/LDH)
                if lab_rng.random() < 0.02:
                    order.status = OrderStatus.CANCELLED
                    continue  # specimen lost/rejected
                if canon in ("K", "LDH") and lab_rng.random() < 0.03:
                    # Hemolyzed sample → falsely elevated K/LDH, flagged
                    result_time = calculate_result_time_from_state(order, hospital_state, hospital_ops or {}, lab_rng)
                    hemolyzed_val = true_labs[canon] * float(lab_rng.uniform(1.2, 1.8))
                    lab_tech = assign_staff("lab_result", "", roster, lab_rng).get("performing_technician", "TECH-001")
                    order.result = OrderResult(
                        result_datetime=result_time, performed_by=lab_tech,
                        lab_name=canon, value=round(hemolyzed_val, 1),
                        unit=get_lab_unit(canon), flag="H*",
                    )
                    order.status = OrderStatus.RESULTED
                    all_lab_results.append(order.result)
                    continue

                result_time = calculate_result_time_from_state(order, hospital_state, hospital_ops or {}, lab_rng)
                observed = generate_lab_result(canon, true_labs[canon], lab_rng)
                flag = determine_flag(canon, observed, sex=patient.sex)
                lab_tech = assign_staff("lab_result", "", roster, lab_rng).get("performing_technician", "TECH-001")
                order.result = OrderResult(
                    result_datetime=result_time, performed_by=lab_tech,
                    lab_name=canon, value=observed,
                    unit=get_lab_unit(canon), flag=flag,
                )
                order.status = OrderStatus.RESULTED
                all_lab_results.append(order.result)

        # === Pass 2: panel children, one isolated sub-RNG per parent specimen.
        # Clinical model: a panel order is **one specimen**, so specimen-rejection
        # fires at most once per parent and cancels every child of that parent.
        # Per-analyte hemolysis is drawn after specimen acceptance. Components not
        # present in true_labs (e.g. BMP Cl/Ca until derive_lab_values produces them)
        # are silently skipped — the child stays PLACED with no result, matching
        # the existing behaviour for any individual order that engine cannot result.
        for parent_id, children in _panel_children_by_parent.items():
            sub_rng = np.random.default_rng(panel_specimen_seed(parent_id))
            if sub_rng.random() < 0.02:
                for child in children:
                    child.status = OrderStatus.CANCELLED
                continue
            for child in children:
                canon = canonical_lab_name(child.display_name)
                if canon not in true_labs:
                    continue  # silently dropped; status stays PLACED
                result_time = calculate_result_time_from_state(
                    child, hospital_state, hospital_ops or {}, sub_rng,
                )
                lab_tech = assign_staff(
                    "lab_result", "", roster, sub_rng,
                ).get("performing_technician", "TECH-001")
                if canon in ("K", "LDH") and sub_rng.random() < 0.03:
                    hemolyzed_val = true_labs[canon] * float(sub_rng.uniform(1.2, 1.8))
                    child.result = OrderResult(
                        result_datetime=result_time, performed_by=lab_tech,
                        lab_name=canon, value=round(hemolyzed_val, 1),
                        unit=get_lab_unit(canon), flag="H*",
                    )
                else:
                    observed = generate_lab_result(canon, true_labs[canon], sub_rng)
                    flag = determine_flag(canon, observed, sex=patient.sex)
                    child.result = OrderResult(
                        result_datetime=result_time, performed_by=lab_tech,
                        lab_name=canon, value=observed,
                        unit=get_lab_unit(canon), flag=flag,
                    )
                child.status = OrderStatus.RESULTED
                all_lab_results.append(child.result)

        # Diagnosis update
        if day >= 1:
            findings = _extract_findings(all_lab_results, disease_id, day)
            if findings:
                protocol_lr = protocol.likelihood_ratios if hasattr(protocol, 'likelihood_ratios') and protocol.likelihood_ratios else None
                protocol_diagnostic = protocol.diagnostic if hasattr(protocol, 'diagnostic') else {}
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
        if rng.random() < 0.3:  # 30% chance of ±1 day shift
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
                all_orders.append(Order(
                    order_id=f"ORD-{patient.patient_id}-MOD-D{day}-{lab_name[:5]}",
                    patient_id=patient.patient_id, order_type=OrderType.LAB,
                    display_name=lab_name, urgency="stat",
                    clinical_intent=f"Day {day} {archetype}: additional workup",
                    ordered_datetime=admission_time + timedelta(days=day, hours=10),
                    status=OrderStatus.PLACED,
                ))
            # Add imaging
            for img_name in mod.get("add_imaging", []):
                all_orders.append(Order(
                    order_id=f"ORD-{patient.patient_id}-MOD-D{day}-IMG",
                    patient_id=patient.patient_id, order_type=OrderType.IMAGING,
                    display_name=img_name, urgency="stat",
                    clinical_intent=f"Day {day} {archetype}: additional imaging",
                    ordered_datetime=admission_time + timedelta(days=day, hours=10),
                    status=OrderStatus.PLACED,
                ))

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
                all_orders.append(Order(
                    order_id=f"ORD-{patient.patient_id}-STOP-D{day}-{stop_idx}-{drug_name[:8]}",
                    patient_id=patient.patient_id, order_type=OrderType.MEDICATION,
                    display_name=f"DISCONTINUE: {drug_name}",
                    urgency="routine",
                    clinical_intent=f"Day {day} {archetype}: stop {drug_name}",
                    ordered_datetime=admission_time + timedelta(days=day, hours=10),
                    status=OrderStatus.PLACED,
                ))
            # Start new medications or procedures
            start_meds = mod.get("start", {}).get(country_key, mod.get("start", []))
            if isinstance(start_meds, list):
                for med in start_meds:
                    if not isinstance(med, dict):
                        continue
                    drug = med.get("drug", "").strip()
                    proc = med.get("procedure", "").strip()
                    if drug:
                        # Medication order
                        display = f"{drug} {med.get('dose', '')}".strip()
                        all_orders.append(Order(
                            order_id=f"ORD-{patient.patient_id}-START-D{day}-{drug[:8]}",
                            patient_id=patient.patient_id, order_type=OrderType.MEDICATION,
                            display_name=display,
                            urgency="urgent",
                            clinical_intent=f"Day {day} {archetype}: new medication",
                            ordered_datetime=admission_time + timedelta(days=day, hours=10),
                            status=OrderStatus.PLACED,
                        ))
                    elif proc:
                        # Procedure order (not a medication)
                        detail = med.get("detail", "")
                        display = f"{proc}" + (f" ({detail})" if detail else "")
                        all_orders.append(Order(
                            order_id=f"ORD-{patient.patient_id}-PROC-D{day}-{proc[:8]}",
                            patient_id=patient.patient_id, order_type=OrderType.PROCEDURE,
                            display_name=display,
                            urgency="urgent",
                            clinical_intent=f"Day {day} {archetype}: new procedure",
                            ordered_datetime=admission_time + timedelta(days=day, hours=10),
                            status=OrderStatus.PLACED,
                        ))
                    # Skip entries with neither drug nor procedure

        # Treatment escalation: if inflammation not improving by day 3, escalate
        if day == 3 and state.inflammation_level > 0.3:
            escalation_drugs = protocol.drugs.get("escalation", {}).get(country_key, [])
            if isinstance(escalation_drugs, dict):
                escalation_drugs = [escalation_drugs]
            for esc_drug in escalation_drugs:
                if not isinstance(esc_drug, dict):
                    continue
                drug_name = esc_drug.get("drug", "")
                dose = esc_drug.get("dose", "")
                indication = esc_drug.get("indication", "no improvement")
                all_orders.append(Order(
                    order_id=f"ORD-{patient.patient_id}-ESC-D{day}-{drug_name[:8]}",
                    encounter_id=encounter_id,
                    patient_id=patient.patient_id,
                    order_type=OrderType.MEDICATION,
                    order_code=esc_drug.get("code_yj", esc_drug.get("code_rxnorm", "")),
                    display_name=f"{drug_name} {dose}".strip(),
                    urgency="urgent",
                    clinical_intent=f"Escalation day {day}: {drug_name} ({indication})",
                    ordered_datetime=admission_time + timedelta(days=day, hours=10),
                    ordered_by=attending_id,
                    status=OrderStatus.PLACED,
                    route=esc_drug.get("route", "IV"),
                ))

        # Medication administration (MAR)
        mars_today = _generate_mar(patient, all_orders, day, admission_time, department=department, roster=roster, rng=rng)
        all_mars.extend(mars_today)

        # Diet order (only when diet changes: NPO → clear liquid → soft → regular)
        if day == 0:
            diet = "NPO"
        elif day == 1 and state.inflammation_level > 0.3:
            diet = "clear_liquid"
        elif state.inflammation_level > 0.2:
            diet = "soft_diet"
        else:
            diet = "regular_diet"
        if diet != prev_diet:
            all_orders.append(Order(
                order_id=f"ORD-{patient.patient_id}-DIET-D{day}",
                patient_id=patient.patient_id,
                order_type=OrderType.DIET,
                display_name=diet,
                urgency="routine",
                clinical_intent=f"Day {day} diet: {diet}",
                ordered_datetime=admission_time + timedelta(days=day, hours=7),
                ordered_by=attending_id,
                status=OrderStatus.PLACED,
            ))
            prev_diet = diet

        # Vitals
        ward_nurse_id = assign_staff("medication_administration", department, roster, rng).get("administering_nurse", "NS-001")
        vitals_country = "JP" if country_key == "japan" else "US"
        vitals_today = _generate_vitals(state, patient, day, admission_time, rng, disease_id=disease_id, nurse_id=ward_nurse_id, country=vitals_country)
        all_vitals.extend(vitals_today)

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
            triggered = evaluate_complications(day, state, patient, comp_list, active_complications, rng)
            for comp in triggered:
                for var, delta in comp.get("state_impact", {}).items():
                    cur = getattr(state, var, None)
                    if cur is not None:
                        setattr(state, var, max(-1.0, min(1.0, cur + delta)))
                comp_name = comp.get("name", "unknown")
                complications_occurred.append(comp_name)
                if "icu_transfer" in comp.get("actions", []):
                    icu_transferred = True
                # Cancel contraindicated meds when AKI develops as complication
                if comp_name == "acute_kidney_injury":
                    for o in all_orders:
                        if o.order_type == OrderType.MEDICATION and o.status == OrderStatus.PLACED:
                            if "metformin" in (o.display_name or "").lower():
                                o.status = OrderStatus.CANCELLED

        # Mortality (disease-specific rate from YAML benchmarks)
        benchmark_mortality = (protocol.outcome_benchmarks.get(country_key, {})
                               .get("in_hospital_mortality", 0.0))
        if _evaluate_mortality(
            state, patient, severity=severity_str, day=day, rng=rng,
            disease_mortality_rate=benchmark_mortality,
            target_los=target_los,
        ):
            death_occurred = True
            break

        # Early discharge: if state-based criteria met before target_los
        if day >= min_los and not death_occurred:
            if _check_discharge_ready(state, day, country_key):
                break  # actual_los = day + 1

    try:
        actual_los = day + 1
    except NameError:
        actual_los = max(1, target_los)
    return {
        "orders": all_orders, "lab_results": all_lab_results, "vitals": all_vitals,
        "mars": all_mars, "io_records": all_io, "adl_assessments": all_adl,
        "state_history": state_history,
        "complications": complications_occurred, "death_occurred": death_occurred,
        "icu_transferred": icu_transferred, "differential": differential,
        "actual_los": actual_los,
    }


# ============================================================
# Medication Administration Records (MAR)
# ============================================================
# Home medications and chronic monitoring
# ============================================================

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
    from clinosim.locale.loader import load_chronic_medications
    chronic_meds = load_chronic_medications()

    orders: list[Order] = []
    monitoring: list[dict] = []
    med_idx = 0

    for condition in patient.chronic_conditions:
        code = condition.code
        spec = chronic_meds.get(code) or chronic_meds.get(code.split(".")[0])
        if not spec:
            continue

        # Home medications (with YAML-driven holds + renal dose adjustment)
        has_ckd = any(c.code.startswith("N18") for c in patient.chronic_conditions)
        renal_reserve = patient.physiological_profile.renal_reserve if hasattr(patient, "physiological_profile") else 1.0
        initial_renal = state.renal_function if state else renal_reserve
        has_renal_impairment = has_ckd or initial_renal < 0.4

        # Build held drug set from disease protocol's medication_holds (YAML-driven)
        held_drugs: set[str] = set()
        hold_reasons: dict[str, str] = {}
        if protocol and hasattr(protocol, "medication_holds"):
            for hold in (protocol.medication_holds or []):
                reason = hold.get("reason", "disease-specific hold")
                for drug in hold.get("drugs", []):
                    held_drugs.add(drug.lower())
                    hold_reasons[drug.lower()] = reason

        for med in spec.get("medications", []):
            prob = med.get("probability", 1.0)
            if prob < 1.0 and rng.random() > prob:
                continue

            drug_name = med["drug"]
            intent = f"Home medication (continue): {code} - {drug_name}"

            # 1. YAML-driven disease-specific holds (highest priority)
            drug_lower = drug_name.lower()
            yaml_held = False
            for held_name in held_drugs:
                if held_name in drug_lower:
                    reason = hold_reasons.get(held_name, "disease-specific hold")
                    yaml_held = True
                    break
            if yaml_held:
                continue  # silently skip — not ordered

            # 2. Metformin: renal-function-based hold (fallback for diseases without YAML holds)
            if "metformin" in drug_lower and (initial_renal < 0.4 or has_renal_impairment):
                continue

            # 3. Renal dose adjustment for CKD patients
            if has_renal_impairment and renal_reserve < 0.5:
                renal_drugs = ["enoxaparin", "enalapril", "candesartan",
                               "alendronate", "celecoxib"]
                if any(rd in drug_lower for rd in renal_drugs):
                    if "celecoxib" in drug_lower:
                        continue  # held
                    else:
                        intent += " [dose reduced for renal impairment]"

            order = Order(
                order_id=f"ORD-{patient.patient_id}-HM-{med_idx:02d}",
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
            )
            orders.append(order)
            med_idx += 1

        # Monitoring specs (passed to daily loop)
        for mon in spec.get("monitoring", []):
            monitoring.append(mon)

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
                    admission_time.year, admission_time.month, admission_time.day,
                    hour, 0,
                ) + timedelta(days=day)
                if order_time < admission_time:
                    continue
                orders.append(Order(
                    order_id=f"ORD-{patient_id}-CM-D{day:02d}-{i:02d}-{t_idx}",
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
                ))
            continue

        if freq == "tid":
            times = [8, 14, 20]
            for t_idx, hour in enumerate(times):
                order_time = datetime(
                    admission_time.year, admission_time.month, admission_time.day,
                    hour, 0,
                ) + timedelta(days=day)
                if order_time < admission_time:
                    continue
                orders.append(Order(
                    order_id=f"ORD-{patient_id}-CM-D{day:02d}-{i:02d}-{t_idx}",
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
                ))
            continue

        # Default: daily at 06:00
        order_time = datetime(
            admission_time.year, admission_time.month, admission_time.day, 6, 0,
        ) + timedelta(days=day)
        orders.append(Order(
            order_id=f"ORD-{patient_id}-CM-D{day:02d}-{i:02d}",
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
        ))

    return orders


# ============================================================

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
    nurse_id = assign_staff("medication_administration", department, roster, rng).get("administering_nurse", "NS-001")

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

        for hour in admin_hours:
            scheduled = datetime(
                admission_time.year, admission_time.month, admission_time.day, hour, 0
            ) + timedelta(days=day)

            if scheduled < admission_time:
                continue

            # Determine status
            status = "given"
            hold_reason = None

            # Hold conditions (clinical)
            if "antihypertensive" in drug_name.lower() and hasattr(patient, 'baseline_vitals'):
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
            mars.append(MedicationAdministration(
                order_id=order.order_id,
                drug_name=drug_name,
                scheduled_datetime=scheduled,
                actual_datetime=actual,
                status=status,
                dose=dose_text,
                route=order.route or _determine_route(drug_name, order.clinical_intent),
                administered_by=nurse_id,
                hold_reason=hold_reason,
            ))

    return mars


# ============================================================
# Vitals generation
# ============================================================

def _generate_adl_assessment(
    state: PhysiologicalState,
    patient: PatientProfile,
    day: int,
    admission_time: datetime,
    rng: np.random.Generator,
) -> dict | None:
    """Generate ADL (Barthel Index) assessment. Done on admission, weekly, and discharge."""
    from clinosim.types.encounter import ADLAssessment

    # ADL assessed on admission (day 0), weekly (day 7, 14...), and approaching discharge
    if day != 0 and day % 7 != 0:
        return None

    # Base score depends on age and clinical state
    age = patient.age
    base = 100
    if age >= 85:
        base -= 20
    elif age >= 75:
        base -= 10

    # Acute illness reduces ADL
    infl_penalty = int(state.inflammation_level * 30)
    perf_penalty = int((1.0 - state.perfusion_status) * 20)
    renal_penalty = int((1.0 - state.renal_function) * 10)

    # Day 0: worst ADL (acute admission)
    if day == 0:
        total = max(0, base - infl_penalty - perf_penalty - renal_penalty - 15)
    else:
        # Gradual recovery
        recovery = min(day * 3, 30)  # up to +30 over time
        total = max(0, min(100, base - infl_penalty - perf_penalty + recovery))

    total = int(rng.normal(total, 5))
    total = max(0, min(100, total))

    # Distribute across components proportionally
    ratio = total / 100.0
    return ADLAssessment(
        date=(admission_time + timedelta(days=day)).date(),
        barthel_score=total,
        feeding=int(10 * min(1, ratio + 0.1)),
        bathing=int(5 * ratio),
        grooming=int(5 * min(1, ratio + 0.1)),
        dressing=int(10 * ratio),
        bowel_control=int(10 * min(1, ratio + 0.2)),
        bladder_control=int(10 * min(1, ratio + 0.15)),
        toilet_use=int(10 * ratio),
        transfers=int(15 * ratio),
        mobility=int(15 * ratio),
        stairs=int(10 * max(0, ratio - 0.2)),
    )


def _generate_daily_io(
    state: PhysiologicalState,
    patient: PatientProfile,
    day: int,
    admission_time: datetime,
    rng: np.random.Generator,
) -> dict:
    """Generate daily intake/output record."""
    from clinosim.types.encounter import IntakeOutputRecord

    # IV fluid: higher in early days, less as patient improves
    if day <= 2:
        iv = int(rng.normal(1500, 300))  # aggressive hydration
    elif state.volume_status < -0.2:
        iv = int(rng.normal(1200, 200))  # dehydrated
    else:
        iv = int(rng.normal(500, 200))  # maintenance

    # Oral intake: improves as patient recovers
    if day == 0:
        oral = int(rng.normal(200, 100))  # NPO or minimal
    elif state.inflammation_level > 0.3:
        oral = int(rng.normal(500, 200))  # poor appetite
    else:
        oral = int(rng.normal(1200, 300))  # recovering

    # Urine output: correlates with renal function and hydration
    base_urine = 1500 * state.renal_function
    urine_sd = max(100, base_urine * 0.2)  # SD proportional to base
    urine = int(max(50, rng.normal(base_urine, urine_sd)))  # min 50ml (anuria threshold)

    # Drain (post-surgical only, simplified)
    drain = 0

    iv = max(0, iv)
    oral = max(0, oral)
    total_in = iv + oral
    total_out = urine + drain
    net = total_in - total_out

    io_date = (admission_time + timedelta(days=day)).date()
    return IntakeOutputRecord(
        date=io_date,
        intake_iv_ml=iv, intake_oral_ml=oral,
        output_urine_ml=urine, output_drain_ml=drain,
        net_balance_ml=net,
    )


_RESPIRATORY_DISEASES = {
    "bacterial_pneumonia", "aspiration_pneumonia", "copd_exacerbation",
    "asthma_exacerbation", "pulmonary_embolism",
}
_NEURO_DISEASES = {
    "cerebral_infarction", "hemorrhagic_stroke", "subdural_hematoma",
    "diabetic_ketoacidosis", "sepsis", "liver_cirrhosis_decompensated",
}


def _make_raw(state, patient, vit_time, rng):
    return derive_observed_vitals(state, patient.baseline_vitals, vit_time, rng)


def _o2_for(spo2, disease_id, rng):
    """Return (on_o2, flow, device)."""
    needs = spo2 < 92 or disease_id in _RESPIRATORY_DISEASES or disease_id == "heart_failure_exacerbation"
    if not needs:
        return False, None, ""
    if spo2 < 88:
        flow = float(rng.uniform(6, 10))
        device = "non-rebreather" if flow >= 8 else "simple_mask"
    elif spo2 < 92:
        flow = float(rng.uniform(2, 5))
        device = "nasal_cannula" if flow <= 4 else "simple_mask"
    else:
        flow = float(rng.uniform(1, 3))
        device = "nasal_cannula"
    return True, flow, device


def _loc_for(state, disease_id, day, rng):
    """Infer AVPU consciousness level."""
    if state.perfusion_status < 0.4:
        return "V" if rng.random() < 0.7 else "P"
    if state.perfusion_status < 0.6 and disease_id in _NEURO_DISEASES:
        return "V" if rng.random() < 0.5 else "A"
    if disease_id in ("hemorrhagic_stroke", "subdural_hematoma") and day <= 2:
        return str(rng.choice(["A", "V", "P"], p=[0.4, 0.4, 0.2]))
    return "A"


def _generate_vitals(
    state: PhysiologicalState,
    patient: PatientProfile,
    day: int,
    admission_time: datetime,
    rng: np.random.Generator,
    disease_id: str = "",
    nurse_id: str = "",
    country: str = "US",
) -> list[VitalSignRecord]:
    """Generate vital sign measurements for this day.

    Realistic patterns:
    - Routine full vitals (T/HR/BP/RR/SpO2) at scheduled rounds (acuity-based frequency)
    - Continuous bedside monitoring (HR/SpO2 only) for unstable / respiratory patients
    - Event-driven re-checks: febrile recheck (Temp only), low SpO2 recheck
    - Within-set time offsets (BP/HR same moment, Temp ±30s, RR ±60s)
    """
    vitals: list[VitalSignRecord] = []
    is_unstable = state.perfusion_status < 0.5 or state.inflammation_level > 0.5
    is_respiratory = disease_id in _RESPIRATORY_DISEASES or disease_id == "heart_failure_exacerbation"

    # Routine full-vitals schedule by acuity
    # Critically unstable (septic shock, acute MI, hemorrhagic stroke): q1-2h
    is_critical = (state.perfusion_status < 0.3
                   or disease_id in ("sepsis", "acute_mi", "hemorrhagic_stroke",
                                     "traffic_accident_severe"))
    if is_critical and day <= 2:
        full_hours = list(range(0, 24, 2))   # q2h (12 sets/day)
    elif is_unstable:
        full_hours = [2, 6, 10, 14, 18, 22]  # q4h (6 sets/day)
    elif day <= 2:
        full_hours = [0, 6, 12, 18]          # q6h
    elif state.inflammation_level < 0.1 and day >= 7:
        full_hours = [6, 18]                 # bid (stable, late stay)
    else:
        full_hours = [6, 14, 22]             # tid

    def _emit(time: datetime, *, fields: set[str], raw: dict, note: str = "") -> None:
        """Emit a VitalSignRecord with only the specified fields populated."""
        on_o2, o2_flow, o2_device = (False, None, "")
        if "spo2" in fields:
            on_o2, o2_flow, o2_device = _o2_for(raw["spo2"], disease_id, rng)
        loc = _loc_for(state, disease_id, day, rng) if "loc" in fields else ""
        # Pain only with full set
        pain = None
        if "pain" in fields:
            base_pain = state.inflammation_level * 4
            if day <= 2:
                base_pain += 2
            pain = int(max(0, min(10, rng.normal(base_pain, 1.5))))
        vitals.append(VitalSignRecord(
            timestamp=time,
            temperature_celsius=round(raw["temperature"], 1) if "temp" in fields else None,
            heart_rate=int(round(raw["heart_rate"])) if "hr" in fields else None,
            systolic_bp=int(round(raw["systolic_bp"])) if "bp" in fields else None,
            diastolic_bp=int(round(raw["diastolic_bp"])) if "bp" in fields else None,
            respiratory_rate=int(round(raw["respiratory_rate"])) if "rr" in fields else None,
            spo2=round(raw["spo2"], 1) if "spo2" in fields else None,
            pain_score=pain,
            consciousness_level=loc,
            on_supplemental_oxygen=on_o2,
            oxygen_flow_rate_lpm=round(o2_flow, 1) if o2_flow else None,
            oxygen_delivery_device=o2_device,
            nursing_note=note,
            measured_by=nurse_id,
            data_source="manual",
        ))

    # 1. Routine full vitals at scheduled rounds
    for hour in full_hours:
        vit_time = datetime(admission_time.year, admission_time.month, admission_time.day, hour, 0) + timedelta(days=day)
        if vit_time < admission_time:
            continue
        raw = _make_raw(state, patient, vit_time, rng)
        actual_time = vit_time + timedelta(minutes=float(rng.normal(0, 10)))

        # CIF stores English nursing notes (AD-30). JP translation at FHIR output.
        note_parts = []
        if raw["temperature"] >= 38.0:
            note_parts.append("febrile")
        if raw["spo2"] < 93:
            note_parts.append("SpO2 low, O2 adjusted")
        if state.inflammation_level < 0.1 and day >= 3:
            note_parts.append("improving, appetite good")
        if day == 0 and hour == full_hours[0]:
            note_parts.append("admission assessment completed")
        note = ". ".join(note_parts) + "." if note_parts else ""

        _emit(actual_time,
              fields={"temp", "hr", "bp", "rr", "spo2", "pain", "loc"},
              raw=raw, note=note)

        # 1a. Febrile re-check: re-measure temperature 30-60 min later
        if raw["temperature"] >= 38.5 and rng.random() < 0.7:
            recheck_time = actual_time + timedelta(minutes=int(rng.uniform(30, 60)))
            recheck_raw = _make_raw(state, patient, recheck_time, rng)
            _emit(recheck_time, fields={"temp"}, raw=recheck_raw,
                  note=f"febrile recheck after {recheck_time.minute - actual_time.minute} min")

    # 2. Continuous bedside monitoring (HR + SpO2 only) every ~2h
    #    for unstable / respiratory / cardiac patients
    if is_unstable or is_respiratory:
        full_hour_set = set(full_hours)
        # Pick hours not already covered by full vitals
        monitor_hours = [h for h in range(1, 24, 2) if h not in full_hour_set]
        for hour in monitor_hours:
            mon_time = datetime(admission_time.year, admission_time.month, admission_time.day, hour, 0) + timedelta(days=day)
            if mon_time < admission_time:
                continue
            mon_time += timedelta(minutes=float(rng.normal(0, 5)))
            raw = _make_raw(state, patient, mon_time, rng)
            _emit(mon_time, fields={"hr", "spo2"}, raw=raw,
                  note="continuous monitor")

    return vitals


# ============================================================
# Discharge prescription
# ============================================================

def _build_discharge_rx(
    patient: PatientProfile,
    disease_id: str,
    protocol: DiseaseProtocol,
    prescriber_id: str,
    admission_time: datetime,
    rng: np.random.Generator,
    country_key: str = "japan",
    final_renal_function: float = 1.0,
) -> PrescriptionRecord:
    """Build discharge prescription from protocol.

    Applies renal contraindication checks so that nephrotoxic drugs or drugs
    requiring renal clearance are not prescribed at discharge if the patient's
    renal function is impaired.
    """
    items: list[dict] = []

    # Drugs contraindicated at low renal function (eGFR roughly maps to state value)
    renal_hold_drugs = {"metformin", "celecoxib", "ibuprofen", "naproxen",
                         "enoxaparin", "alendronate"}

    discharge_drugs = protocol.drugs.get("discharge_oral", {}).get(country_key, [])
    if isinstance(discharge_drugs, dict):
        discharge_drugs = [discharge_drugs]

    for drug_spec in discharge_drugs:
        if isinstance(drug_spec, dict):
            drug_name = drug_spec.get("drug", "")
            # Renal contraindication check at discharge
            if final_renal_function < 0.3 and any(
                rd in drug_name.lower() for rd in renal_hold_drugs
            ):
                continue  # skip nephrotoxic drug
            items.append({
                "drug_name": drug_name,
                "dose": drug_spec.get("dose", ""),
                "duration_days": drug_spec.get("duration_days", 7),
                "route": drug_spec.get("route", "PO"),
            })

    # Continue chronic medications (with renal check)
    for med in patient.current_medications:
        if final_renal_function < 0.3 and any(
            rd in med.lower() for rd in renal_hold_drugs
        ):
            continue  # do not restart nephrotoxic drug at discharge
        items.append({"drug_name": med, "dose": "", "route": "PO", "duration_days": 28})

    return PrescriptionRecord(
        prescription_id=f"RX-{patient.patient_id}-DC",
        patient_id=patient.patient_id,
        prescriber_id=prescriber_id,
        issue_date=admission_time,
        items=items,
    )


# ============================================================
# Findings extraction for diagnosis
# ============================================================

def _extract_findings(
    lab_results: list[OrderResult],
    disease_id: str,
    day: int,
) -> list[tuple[str, bool]]:
    """Extract diagnostic findings from lab results for Bayesian update."""
    findings: list[tuple[str, bool]] = []

    recent = lab_results[-10:]  # last few results
    for r in recent:
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


# ============================================================
# Unknown condition simulation
# ============================================================

def _simulate_unknown_condition(
    patient: PatientProfile,
    event: LifeEvent,
    rng: np.random.Generator,
    healthcare: HealthcareSystemConfig,
    roster: StaffRoster,
    hospital_ops: dict | None = None,
    config: SimulatorConfig | None = None,
) -> CIFPatientRecord | None:
    """Simulate patient with unknown/idiopathic condition.

    Unlike known-disease patients, unknown condition patients undergo extensive
    diagnostic workup that progressively broadens without reaching a conclusion.
    """
    state = initialize_state(patient.physiological_profile, patient.chronic_conditions, patient.patient_id)
    state.inflammation_level += float(rng.uniform(0.10, 0.30))

    admission_time = datetime(event.timestamp.year, event.timestamp.month, event.timestamp.day,
                               int(rng.integers(8, 22)), 0)
    state.timestamp = admission_time
    complaint = event.disease_id.replace("unknown_", "").replace("_", " ")
    encounter = create_inpatient_encounter(patient.patient_id, admission_time, chief_complaint=complaint)
    # Unknown conditions are managed by internal medicine — resolve via hospital config
    from clinosim.simulator.helpers import resolve_department, pick_ward
    department = resolve_department("internal_medicine", hospital_ops)
    encounter.department_id = department
    attending_id = assign_staff("admission", department, roster, rng).get("attending_physician", "DR-001")
    encounter.attending_physician_id = attending_id
    encounter.ward_id = pick_ward(department, hospital_ops, rng)
    ward_cap = (hospital_ops or {}).get("ward_capacity", {}).get(encounter.ward_id, 10)
    bed_idx = int(rng.integers(1, ward_cap + 1))
    encounter.bed_number = f"{encounter.ward_id}-{bed_idx:02d}"

    target_los = int(rng.integers(7, 14))  # unknown conditions: longer workup
    all_vitals: list[VitalSignRecord] = []
    all_orders: list[Order] = []
    all_lab_results: list[OrderResult] = []
    state_history = [deepcopy(state)]
    has_diabetes = any(c.code.startswith("E11") for c in patient.chronic_conditions)

    # Extensive admission workup (broader than known-disease)
    admission_labs = ["CRP", "WBC", "Hb", "Plt", "Creatinine", "Na", "K", "Glucose",
                      "AST", "ALT", "ALP", "LDH", "Albumin", "PT_INR", "PCT"]
    for i, lab_name in enumerate(admission_labs):
        all_orders.append(Order(
            order_id=f"ORD-{patient.patient_id}-ADM-L{i:02d}",
            patient_id=patient.patient_id, order_type=OrderType.LAB,
            display_name=lab_name, urgency="stat",
            clinical_intent=f"Unknown {complaint}: initial workup",
            ordered_datetime=admission_time, ordered_by=attending_id,
            status=OrderStatus.PLACED,
        ))

    # Imaging: CXR + CT (broader search)
    for i, img in enumerate(["Chest_Xray", "CT_abdomen_pelvis"]):
        all_orders.append(Order(
            order_id=f"ORD-{patient.patient_id}-ADM-I{i:02d}",
            patient_id=patient.patient_id, order_type=OrderType.IMAGING,
            display_name=img, urgency="stat" if i == 0 else "urgent",
            clinical_intent=f"Unknown {complaint}: imaging workup",
            ordered_datetime=admission_time + timedelta(hours=i + 1),
            ordered_by=attending_id, status=OrderStatus.PLACED,
        ))

    # Supportive medications (even unknown conditions need basic care)
    supportive_meds = [
        {"drug": "Acetaminophen 500mg PO q6h PRN", "intent": "antipyretic for fever"},
        {"drug": "IV_fluid: NS 80mL/h", "intent": "hydration"},
    ]
    # If fever is the complaint, empiric antibiotics may be started
    if "fever" in complaint:
        supportive_meds.append({"drug": "Ceftriaxone 1g IV daily", "intent": "empiric antibiotic (pending workup)"})

    for i, med in enumerate(supportive_meds):
        all_orders.append(Order(
            order_id=f"ORD-{patient.patient_id}-ADM-M{i:02d}",
            patient_id=patient.patient_id, order_type=OrderType.MEDICATION,
            display_name=med["drug"], urgency="routine",
            clinical_intent=f"Unknown {complaint}: {med['intent']}",
            ordered_datetime=admission_time + timedelta(minutes=30),
            ordered_by=attending_id, status=OrderStatus.PLACED,
        ))
    all_mars: list[MedicationAdministration] = []

    for day in range(target_los):
        # State: slow random walk (no clear trajectory)
        state.inflammation_level += float(rng.normal(0, 0.02))
        state.inflammation_level = max(0.0, min(1.0, state.inflammation_level))
        state_history.append(deepcopy(state))

        # Daily labs (more frequent than known-disease: still investigating)
        if day >= 1:
            daily_labs = ["CRP", "WBC", "Creatinine"]
            # Additional workup on specific days
            if day == 2:
                daily_labs.extend(["Ferritin", "LDH", "PCT"])  # infection/tumor markers
            if day == 4:
                daily_labs.extend(["ANA", "RF"])  # autoimmune screening
                # Additional imaging
                all_orders.append(Order(
                    order_id=f"ORD-{patient.patient_id}-D4-IMG",
                    patient_id=patient.patient_id, order_type=OrderType.IMAGING,
                    display_name="CT_chest_with_contrast", urgency="routine",
                    clinical_intent="Day 4: expanded imaging for unknown fever",
                    ordered_datetime=admission_time + timedelta(days=4, hours=10),
                    ordered_by=attending_id, status=OrderStatus.PLACED,
                ))

            for i, lab_name in enumerate(daily_labs):
                lab_time = admission_time + timedelta(days=day, hours=6)
                all_orders.append(Order(
                    order_id=f"ORD-{patient.patient_id}-D{day}-L{i:02d}",
                    patient_id=patient.patient_id, order_type=OrderType.LAB,
                    display_name=lab_name, urgency="routine",
                    clinical_intent=f"Day {day}: monitoring + workup",
                    ordered_datetime=lab_time, ordered_by=attending_id,
                    status=OrderStatus.PLACED,
                ))

        # Generate lab results. _simulate_unknown_condition has no disease
        # protocol by definition — scenario flags (causes_myocardial_injury,
        # causes_vte) are all-False here, matching scenario_flags_from_protocol(None).
        # Phase 2b: chronic warfarin from patient.current_medications still
        # applies (AF chronic patient hospitalized for unknown condition has
        # therapeutic INR). Pass medication_orders=None / current_day=None so
        # only the chronic detection path runs.
        _flags_unknown = medication_flags_from_context(patient)
        true_labs = derive_lab_values(state, sex=patient.sex, age=patient.age, has_diabetes=has_diabetes, **_flags_unknown)
        for order in all_orders:
            if order.order_type.value == "lab" and order.status == OrderStatus.PLACED and order.display_name in true_labs:
                result_time = calculate_result_time_from_state(order, None, {}, rng)  # unknown condition: no hospital state
                observed = generate_lab_result(order.display_name, true_labs[order.display_name], rng)
                flag = determine_flag(order.display_name, observed, sex=patient.sex)
                tech_id = assign_staff("lab_result", "", roster, rng).get("performing_technician", "TECH-001")
                order.result = OrderResult(
                    result_datetime=result_time, performed_by=tech_id,
                    lab_name=order.display_name, value=observed,
                    unit=get_lab_unit(order.display_name), flag=flag,
                )
                order.status = OrderStatus.RESULTED
                all_lab_results.append(order.result)

        # Vitals
        unk_nurse_id = assign_staff("medication_administration", department, roster, rng).get("administering_nurse", "NS-001")
        all_vitals.extend(_generate_vitals(state, patient, day, admission_time, rng, nurse_id=unk_nurse_id))

        # MAR for supportive medications
        all_mars.extend(_generate_mar(patient, all_orders, day, admission_time, department=department, roster=roster, rng=rng))

    encounter.status = EncounterStatus.COMPLETED
    encounter.discharge_datetime = admission_time + timedelta(days=target_los, hours=14)

    # ~50% of unknown conditions get partially resolved during stay
    # (workup finds something, but not a definitive diagnosis)
    if rng.random() < 0.5:
        discharge_code = "R50.9" if "fever" in event.disease_id else "R53.1"
        discharge_name = "Unresolved " + complaint
    else:
        # Partially resolved: nonspecific diagnosis assigned
        discharge_code = "R50.9" if "fever" in event.disease_id else "R68.8"
        discharge_name = complaint.title() + " (under investigation, outpatient follow-up)"

    # Set encounter_id for all orders that don't have one — mirrors the
    # identical loop in simulate_inpatient (line 361-363). Without this,
    # _fhir_service_request._build_sr_skeleton raises AssertionError on
    # JP cohorts where unknown-condition patients generate ADM-L orders
    # without encounter_id, causing FHIR export to fail.
    for o in all_orders:
        if not o.encounter_id:
            o.encounter_id = encounter.encounter_id

    # Note: unknown-condition encounters intentionally do NOT run the
    # POST_ENCOUNTER stage (device + hai). _simulate_unknown_condition never
    # sets record.icu_transferred = True (line 511 default), and modules/
    # device/engine.place_devices_for_encounter early-returns [] when
    # icu_transferred is False. So the enrichers + apply_hai_lab_lift would
    # uniformly no-op here; the post-PR-90 xhigh review caught a 29-line
    # dead block at this spot and it was removed. If a future requirement
    # adds ICU transfer to unknown-condition simulation, gate the hook on
    # icu_transferred just like every other AD-32-aware code path.
    return CIFPatientRecord(
        patient=patient, encounters=[encounter],
        orders=all_orders, vital_signs=all_vitals, lab_results=all_lab_results,
        medication_administrations=all_mars,
        condition_event=ConditionEvent(condition_id=f"COND-{patient.patient_id}-UNK",
                                       condition_type="unknown", symptom_pattern=event.disease_id),
        clinical_diagnosis=ClinicalDiagnosis(
            admission_diagnosis_code="R50.9" if "fever" in event.disease_id else "R53.1",
            admission_diagnosis_system="icd-10-cm",
            discharge_diagnosis_code=discharge_code,
            discharge_diagnosis_system="icd-10-cm",
            diagnosis_correct=False,
        ),
        physiological_states=state_history,
    )
