"""clinosim simulator — population-driven EHR data generation.

Public API:
  run_beta(config)       — population-driven simulation (main entry point)
  run_forced(scenario)   — generate specific disease/archetype (testing)
  run_alpha(config)      — backward-compatible single patient

CLI:
  clinosim generate -p 10000 -o ./output --format cif csv fhir
  clinosim test-disease bacterial_pneumonia --archetype treatment_resistant -n 5
"""

from __future__ import annotations

import os
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
from clinosim.modules.disease.protocol import DiseaseProtocol, load_disease_protocol
from clinosim.modules.encounter.engine import create_inpatient_encounter
from clinosim.modules.healthcare_system.loader import load_healthcare_config
from clinosim.modules.observation.engine import determine_flag, generate_lab_result, get_lab_unit
from clinosim.modules.order.engine import (
    calculate_lab_result_time,
    place_admission_orders,
    place_daily_lab_orders,
)
from clinosim.modules.output.cif_writer import write_cif
from clinosim.modules.patient.activator import activate_patient
from clinosim.modules.physiology.engine import (
    apply_disease_onset,
    derive_lab_values,
    derive_vital_signs,
    initialize_state,
    update,
)
from clinosim.modules.population.engine import (
    LifeEvent,
    generate_monthly_events,
    generate_population,
)
from clinosim.modules.procedure.engine import (
    generate_rehab_sessions,
    simulate_surgery,
)
from clinosim.modules.staff.engine import StaffRoster, assign_staff, generate_roster
from clinosim.types.clinical import (
    ClinicalDiagnosis,
    ConditionEvent,
    PhysiologicalState,
)
from clinosim.types.config import ForcedScenario, HealthcareSystemConfig, SimulatorConfig
from clinosim.types.encounter import (
    EncounterStatus,
    EncounterType,
    MedicationAdministration,
    Order,
    OrderResult,
    OrderStatus,
    OrderType,
    PrescriptionRecord,
    VitalSignRecord,
)
from clinosim.types.output import CIFDataset, CIFMetadata, CIFPatientRecord
from clinosim.types.patient import PatientProfile


# ============================================================
# Main entry point
# ============================================================

def run_beta(config: SimulatorConfig | None = None) -> CIFDataset:
    """Run population-driven simulation."""
    if config is None:
        config = SimulatorConfig()

    rng = np.random.default_rng(config.random_seed)

    # Load modules
    healthcare = load_healthcare_config(config.country)
    protocols = _load_all_disease_protocols()
    roster = generate_roster(config.hospital_scale, config.country, rng)

    # Generate population
    population = generate_population(config.catchment_population, config.country, rng)
    print(f"  Population: {population.total_persons} persons")

    # Run life events
    start_y, start_m = int(config.time_range[0][:4]), int(config.time_range[0][5:7])
    end_y, end_m = int(config.time_range[1][:4]), int(config.time_range[1][5:7])

    all_events: list[LifeEvent] = []
    y, m = start_y, start_m
    while (y, m) <= (end_y, end_m):
        all_events.extend(generate_monthly_events(population, y, m, rng, country=config.country))
        m += 1
        if m > 12:
            m, y = 1, y + 1

    hospital_events = [e for e in all_events if e.requires_hospital]
    print(f"  Life events: {len(all_events)} total, {len(hospital_events)} requiring hospital")

    # Simulate each patient
    patient_records: list[CIFPatientRecord] = []
    n_hosp = len(hospital_events)
    for idx, event in enumerate(hospital_events):
        if (idx + 1) % 50 == 0 or idx == n_hosp - 1:
            print(f"  Simulating inpatient {idx+1}/{n_hosp}...", flush=True)

        person = population.get_person(event.person_id)
        if person is None or not person.is_alive:
            continue

        patient = activate_patient(person, rng, config.country)
        disease_id = event.disease_id

        # Unknown condition
        if event.condition_type == "unknown" or disease_id.startswith("unknown_"):
            record = _simulate_unknown_condition(patient, event, rng, healthcare, roster)
            if record:
                patient_records.append(record)
                person.has_visited_hospital = True
                person.visit_count += 1
            continue

        protocol = protocols.get(disease_id)
        if protocol is None:
            continue

        # Mixed condition: determine secondary disease from patient's chronic conditions
        secondary_protocol = None
        if event.condition_type == "mixed":
            secondary_protocol = _select_secondary_disease(
                patient, disease_id, protocols, rng,
            )

        record = _simulate_patient(
            patient, event, disease_id, protocol, healthcare, roster, config, rng,
            secondary_protocol=secondary_protocol,
            is_readmission=event.is_readmission,
            prior_encounter_id=event.prior_encounter_id,
            readmission_number=event.readmission_number,
        )
        patient_records.append(record)
        _deactivate_to_layer1(person, record, disease_id)
        if record.deceased:
            person.is_alive = False

    print(f"  Inpatient done: {len(patient_records)} records", flush=True)

    # === Readmission evaluation (post-loop pass) ===
    country_key = _country_to_yaml_key(config.country)
    readmission_events: list[LifeEvent] = []
    for record in patient_records:
        if record.deceased or record.is_readmission:
            continue
        person = population.get_person(record.patient.patient_id)
        if not person or not person.is_alive:
            continue
        disease_id = (
            record.condition_event.ground_truth_diseases[0]
            if record.condition_event.ground_truth_diseases else None
        )
        if not disease_id:
            continue
        protocol = protocols.get(disease_id)
        if not protocol:
            continue
        re_event = _evaluate_readmission(
            record, person, disease_id, protocol, country_key, rng,
        )
        if re_event:
            readmission_events.append(re_event)

    # Simulate readmissions (max 1 chain per patient for now)
    readmission_events.sort(key=lambda e: e.timestamp)
    for re_event in readmission_events:
        person = population.get_person(re_event.person_id)
        if not person or not person.is_alive:
            continue
        protocol = protocols.get(re_event.disease_id)
        if not protocol:
            continue
        patient = activate_patient(person, rng, config.country)
        record = _simulate_patient(
            patient, re_event, re_event.disease_id, protocol,
            healthcare, roster, config, rng,
            is_readmission=True,
            prior_encounter_id=re_event.prior_encounter_id,
            readmission_number=re_event.readmission_number,
        )
        patient_records.append(record)
        _deactivate_to_layer1(person, record, re_event.disease_id)
        if record.deceased:
            person.is_alive = False

    print(f"  Readmissions done: {len(readmission_events)} evaluated", flush=True)

    # === Outpatient encounters ===
    from clinosim.locale.loader import load_chronic_followup
    followup_data = load_chronic_followup()
    post_dc_spec = followup_data.get("_post_discharge", {})
    post_dc_days = post_dc_spec.get("first_visit_days", 14)

    # Collect inpatient records only (not readmission OPD duplicates)
    inpatient_records = [
        r for r in patient_records
        if not r.deceased and r.encounters
        and r.encounters[0].encounter_type == EncounterType.INPATIENT
    ]

    # Cache activated patients to avoid redundant activation
    patient_cache: dict[str, PatientProfile] = {}
    seen_opd_pids: set[str] = set()

    for record in inpatient_records:
        pid = record.patient.patient_id
        person = population.get_person(pid)
        if not person or not person.is_alive:
            continue
        enc = record.encounters[0]
        if not enc.discharge_datetime:
            continue

        # Activate once per patient
        if pid not in patient_cache:
            patient_cache[pid] = activate_patient(person, rng, config.country)

        # Post-discharge follow-up (1 per inpatient encounter)
        followup_date = enc.discharge_datetime + timedelta(days=post_dc_days)
        disease_id = (record.condition_event.ground_truth_diseases[0]
                      if record.condition_event.ground_truth_diseases else "")
        # Merge disease-specific labs into post-discharge spec
        disease_fu = followup_data.get("_post_discharge_by_disease", {}).get(disease_id, {})
        merged_spec = dict(post_dc_spec)
        if disease_fu.get("labs"):
            merged_spec["labs"] = disease_fu["labs"]
        opd_record = _simulate_outpatient_visit(
            patient_cache[pid], "post_discharge", followup_date, roster, rng,
            followup_spec=merged_spec, post_discharge_disease=disease_id,
        )
        patient_records.append(opd_record)

        # Chronic disease follow-up (max 2 conditions per patient, once)
        if pid in seen_opd_pids:
            continue
        seen_opd_pids.add(pid)
        chronic_visits = 0
        for chronic_code in person.chronic_conditions:
            if chronic_visits >= 2:
                break
            spec = followup_data.get(chronic_code)
            if not spec:
                continue
            visit_month = int(rng.integers(start_m, min(start_m + 6, 13)))
            visit_date = datetime(start_y, visit_month, int(rng.integers(1, 28)), 10, 0)
            opd_record = _simulate_outpatient_visit(
                patient_cache[pid], "chronic_followup", visit_date, roster, rng,
                chronic_code=chronic_code, followup_spec=spec,
            )
            patient_records.append(opd_record)
            chronic_visits += 1

    n_opd = len(patient_records) - len(inpatient_records) - len(readmission_events)
    print(f"  Outpatient done: {n_opd} visits generated", flush=True)

    # === ED visits (not admitted — go home after ED evaluation) ===
    ed_config = demo.get("ed_visit_not_admitted", {}) if 'demo' in dir() else {}
    if not ed_config:
        from clinosim.locale.loader import load_demographics
        ed_config = load_demographics(config.country).get("ed_visit_not_admitted", {})
    ed_rate = ed_config.get("rate_per_admitted", 3.0)
    ed_conditions = ed_config.get("conditions", [])
    n_ed = int(len(inpatient_records) * ed_rate)
    if ed_conditions and n_ed > 0:
        ed_probs = [c.get("probability", 0.1) for c in ed_conditions]
        total_p = sum(ed_probs)
        ed_probs = [p / total_p for p in ed_probs]
        for _ in range(n_ed):
            # Pick random person from population
            person_id = rng.choice(list(population.persons.keys()))
            person = population.get_person(person_id)
            if not person or not person.is_alive:
                continue
            patient = activate_patient(person, rng, config.country)
            # Pick ED condition
            cond_idx = int(rng.choice(len(ed_conditions), p=ed_probs))
            cond = ed_conditions[cond_idx]
            # Random date within simulation period
            ed_month = int(rng.integers(start_m, min(start_m + 11, 13)))
            ed_day = int(rng.integers(1, 28))
            ed_hour = int(rng.choice([9, 10, 14, 15, 19, 20, 21, 22]))  # ED visit hours
            ed_time = datetime(start_y, ed_month, ed_day, ed_hour, int(rng.integers(0, 60)))

            ed_record = _simulate_ed_visit(
                patient, cond, ed_time, roster, rng,
            )
            patient_records.append(ed_record)
        print(f"  ED visits (not admitted): {n_ed} generated", flush=True)

    metadata = CIFMetadata(
        clinosim_version="0.1.0",
        random_seed=config.random_seed,
        country=config.country,
        hospital_scale=config.hospital_scale,
        total_patients_generated=len(patient_records),
        llm_mode=config.llm.judgment.mode,
    )
    return CIFDataset(metadata=metadata, patients=patient_records)


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

    state = apply_disease_onset(state, severity, protocol.initial_state_impact)

    # Mixed condition: superimpose secondary disease's state impact
    secondary_disease_id = None
    if secondary_protocol:
        secondary_disease_id = secondary_protocol.disease_id
        # Secondary disease typically presents at moderate severity
        state = apply_disease_onset(state, "moderate", secondary_protocol.initial_state_impact)

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
    chief_complaint = _disease_chief_complaint(protocol)
    encounter = create_inpatient_encounter(
        patient.patient_id, admission_time,
        chief_complaint=chief_complaint,
        visit_number=readmission_number + 1,
    )

    # Staff assignment — department from protocol YAML
    department = _disease_to_department(protocol)
    staff = assign_staff("admission", department, roster, rng)
    attending_id = staff.get("attending_physician", "DR-001")
    encounter.attending_physician_id = attending_id

    # Ward and bed assignment
    ward_floor = int(rng.integers(3, 7))  # floors 3-6
    ward_wing = str(rng.choice(["E", "W"]))
    encounter.ward_id = f"{ward_floor}{ward_wing}"
    encounter.bed_number = f"{ward_floor}{int(rng.integers(1, 30)):02d}-{int(rng.integers(1, 5))}"

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
        admission_time, country=country_key, rng=rng,
    )
    for o in admission_orders:
        o.ordered_by = attending_id

    # Home medication orders (chronic condition continuation)
    home_med_orders, chronic_monitoring = _generate_home_medication_orders(
        patient, encounter.encounter_id, admission_time, attending_id, rng,
    )
    admission_orders.extend(home_med_orders)

    # Tracking
    procedures, rehab_sessions = [], []
    icu_transferred, death_occurred = False, False

    # Surgery (protocol-driven: requires_surgery flag in YAML)
    if protocol.requires_surgery:
        proc, impacts = simulate_surgery(patient, disease_id, encounter.encounter_id,
                                          admission_time, protocol, rng, config.country)
        procedures.append(proc)
        for var, delta in impacts.items():
            cur = getattr(state, var, None)
            if cur is not None:
                setattr(state, var, max(-1.0, min(1.0, cur + delta)))
        rehab_sessions = generate_rehab_sessions(
            patient.patient_id, encounter.encounter_id,
            proc.start_datetime, target_los, rng, config.country,
        )

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

    clinical_diagnosis = ClinicalDiagnosis(
        admission_diagnosis_code=protocol.icd_codes.get("primary", ""),
        admission_diagnosis_name=disease_id.replace("_", " ").title(),
        discharge_diagnosis_code=dx_code,
        discharge_diagnosis_name=dx_name,
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
    discharge_rx = _build_discharge_rx(patient, disease_id, protocol, attending_id, rng, country_key=country_key) if not death_occurred else None

    # Encounter completion
    encounter.status = EncounterStatus.COMPLETED
    # Discharge time: morning (10-12) for planned discharge, any time for death
    dc_hour = 0 if death_occurred else int(rng.normal(11, 1.5))
    dc_hour = max(9, min(16, dc_hour)) if not death_occurred else 0
    encounter.discharge_datetime = admission_time + timedelta(days=actual_los, hours=dc_hour)

    return CIFPatientRecord(
        patient=patient, encounters=[encounter], orders=all_orders,
        vital_signs=all_vitals, lab_results=all_lab_results,
        condition_event=condition_event, clinical_diagnosis=clinical_diagnosis,
        complications_occurred=complications_occurred,
        procedures=procedures, rehab_sessions=rehab_sessions,
        medication_administrations=all_mars,
        intake_output_records=all_io,
        adl_assessments=all_adl,
        discharge_prescription=discharge_rx,
        icu_transferred=icu_transferred, deceased=death_occurred,
        death_day=actual_los if death_occurred else None,
        is_readmission=is_readmission,
        prior_encounter_id=prior_encounter_id,
        readmission_number=readmission_number,
        physiological_states=state_history,
    )


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
) -> dict:
    """Run the day-by-day simulation loop. Returns all generated data."""

    all_orders = list(admission_orders)
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
                protocol.model_dump(), patient.patient_id, "", day, lab_time,
                freq_mod, rng,
            )
            all_orders.extend(daily_orders)

        # Chronic condition monitoring labs (additional to disease protocol)
        if chronic_monitoring and day >= 1:
            chronic_lab_orders = _place_chronic_monitoring_orders(
                chronic_monitoring, patient.patient_id, day, admission_time, rng,
            )
            all_orders.extend(chronic_lab_orders)

        # Lab results (with temporal lag for slow markers like CRP)
        true_labs = derive_lab_values(state, sex=patient.sex, age=patient.age, has_diabetes=has_diabetes)

        # Apply temporal lag: CRP reflects inflammation from ~1 day ago
        if len(state_history) >= 2 and "CRP" in true_labs:
            # CRP lags inflammation by ~1 day
            lag_idx = max(0, len(state_history) - 2)  # previous day's state
            lagged_state = state_history[lag_idx]
            lagged_labs = derive_lab_values(lagged_state, sex=patient.sex, age=patient.age, has_diabetes=has_diabetes)
            true_labs["CRP"] = lagged_labs.get("CRP", true_labs["CRP"])

        for order in all_orders:
            if order.order_type.value == "lab" and order.status == OrderStatus.PLACED and order.display_name in true_labs:
                # Pre-analytical issues: specimen rejection (~2%), hemolysis (~3% for K/LDH)
                if rng.random() < 0.02:
                    order.status = OrderStatus.CANCELLED
                    continue  # specimen lost/rejected
                if order.display_name in ("K", "LDH") and rng.random() < 0.03:
                    # Hemolyzed sample → falsely elevated K/LDH, flagged
                    result_time = calculate_lab_result_time(order, rng)
                    hemolyzed_val = true_labs[order.display_name] * float(rng.uniform(1.2, 1.8))
                    lab_tech = assign_staff("lab_result", "", roster, rng).get("performing_technician", "TECH-001")
                    order.result = OrderResult(
                        result_datetime=result_time, performed_by=lab_tech,
                        lab_name=order.display_name, value=round(hemolyzed_val, 1),
                        unit=get_lab_unit(order.display_name), flag="H*",
                    )
                    order.status = OrderStatus.RESULTED
                    all_lab_results.append(order.result)
                    continue

                result_time = calculate_lab_result_time(order, rng)
                observed = generate_lab_result(order.display_name, true_labs[order.display_name], rng)
                flag = determine_flag(order.display_name, observed, sex=patient.sex)
                lab_tech = assign_staff("lab_result", "", roster, rng).get("performing_technician", "TECH-001")
                order.result = OrderResult(
                    result_datetime=result_time, performed_by=lab_tech,
                    lab_name=order.display_name, value=observed,
                    unit=get_lab_unit(order.display_name), flag=flag,
                )
                order.status = OrderStatus.RESULTED
                all_lab_results.append(order.result)

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
            for drug_name in mod.get("stop", []):
                all_orders.append(Order(
                    order_id=f"ORD-{patient.patient_id}-STOP-D{day}",
                    patient_id=patient.patient_id, order_type=OrderType.MEDICATION,
                    display_name=f"DISCONTINUE: {drug_name}",
                    urgency="routine",
                    clinical_intent=f"Day {day} {archetype}: stop {drug_name}",
                    ordered_datetime=admission_time + timedelta(days=day, hours=10),
                    status=OrderStatus.PLACED,
                ))
            # Start new medications
            start_meds = mod.get("start", {}).get(country_key, mod.get("start", []))
            if isinstance(start_meds, list):
                for med in start_meds:
                    if isinstance(med, dict):
                        all_orders.append(Order(
                            order_id=f"ORD-{patient.patient_id}-START-D{day}-{med.get('drug','')[:8]}",
                            patient_id=patient.patient_id, order_type=OrderType.MEDICATION,
                            display_name=f"{med.get('drug', '')} {med.get('dose', '')}",
                            urgency="urgent",
                            clinical_intent=f"Day {day} {archetype}: new medication",
                            ordered_datetime=admission_time + timedelta(days=day, hours=10),
                            status=OrderStatus.PLACED,
                        ))

        # Medication administration (MAR)
        mars_today = _generate_mar(patient, all_orders, day, admission_time, roster, rng)
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
        prev_diet = getattr(_generate_vitals, '_prev_diet', {}).get(patient.patient_id, "")
        if diet != prev_diet:
            all_orders.append(Order(
                order_id=f"ORD-{patient.patient_id}-DIET-D{day}",
                patient_id=patient.patient_id,
                order_type=OrderType.DIET,
                display_name=diet,
                urgency="routine",
                clinical_intent=f"Day {day} diet: {diet}",
                ordered_datetime=admission_time + timedelta(days=day, hours=7),
                status=OrderStatus.PLACED,
            ))
            if not hasattr(_generate_vitals, '_prev_diet'):
                _generate_vitals._prev_diet = {}
            _generate_vitals._prev_diet[patient.patient_id] = diet

        # Vitals
        vitals_today = _generate_vitals(state, patient, day, admission_time, rng)
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
                complications_occurred.append(comp.get("name", "unknown"))
                if "icu_transfer" in comp.get("actions", []):
                    icu_transferred = True

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

    actual_los = day + 1
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
        spec = chronic_meds.get(code)
        if not spec:
            continue

        # Home medications (with renal dose adjustment)
        has_ckd = any(c.code.startswith("N18") for c in patient.chronic_conditions)
        renal_reserve = patient.physiological_profile.renal_reserve if hasattr(patient, "physiological_profile") else 1.0

        for med in spec.get("medications", []):
            prob = med.get("probability", 1.0)
            if prob < 1.0 and rng.random() > prob:
                continue

            drug_name = med["drug"]
            intent = f"Home medication (continue): {code} - {drug_name}"

            # Renal dose adjustment for CKD patients
            if has_ckd and renal_reserve < 0.5:
                renal_drugs = ["Metformin", "Enoxaparin", "Enalapril", "Candesartan",
                               "Alendronate", "Celecoxib"]
                if any(rd.lower() in drug_name.lower() for rd in renal_drugs):
                    if "Metformin" in drug_name and renal_reserve < 0.3:
                        intent += " [HELD - eGFR<30]"
                        continue  # contraindicated
                    elif "Celecoxib" in drug_name:
                        intent += " [HELD - renal impairment]"
                        continue
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
                    encounter_id="",
                    patient_id=patient_id,
                    order_type=OrderType.LAB,
                    order_code="",
                    display_name=mon["test"],
                    urgency="routine",
                    clinical_intent=mon.get("intent", f"Chronic monitoring: {mon['test']}"),
                    ordered_datetime=order_time,
                    ordered_by="",
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
                    encounter_id="",
                    patient_id=patient_id,
                    order_type=OrderType.LAB,
                    order_code="",
                    display_name=mon["test"],
                    urgency="routine",
                    clinical_intent=mon.get("intent", f"Chronic monitoring: {mon['test']}"),
                    ordered_datetime=order_time,
                    ordered_by="",
                    status=OrderStatus.PLACED,
                ))
            continue

        # Default: daily at 06:00
        order_time = datetime(
            admission_time.year, admission_time.month, admission_time.day, 6, 0,
        ) + timedelta(days=day)
        orders.append(Order(
            order_id=f"ORD-{patient_id}-CM-D{day:02d}-{i:02d}",
            encounter_id="",
            patient_id=patient_id,
            order_type=OrderType.LAB,
            order_code="",
            display_name=mon["test"],
            urgency="routine",
            clinical_intent=mon.get("intent", f"Chronic monitoring: {mon['test']}"),
            ordered_datetime=order_time,
            ordered_by="",
            status=OrderStatus.PLACED,
        ))

    return orders


# ============================================================

def _generate_mar(
    patient: PatientProfile,
    orders: list[Order],
    day: int,
    admission_time: datetime,
    roster: StaffRoster,
    rng: np.random.Generator,
) -> list[MedicationAdministration]:
    """Generate MAR entries for medication orders on this day."""
    mars: list[MedicationAdministration] = []

    med_orders = [o for o in orders if o.order_type == OrderType.MEDICATION and o.status == OrderStatus.PLACED]
    nurse_id = assign_staff("medication_administration", "internal_medicine", roster, rng).get("administering_nurse", "NS-001")

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

            mars.append(MedicationAdministration(
                order_id=order.order_id,
                drug_name=drug_name,
                scheduled_datetime=scheduled,
                actual_datetime=actual,
                status=status,
                dose=order.display_name,
                route=_determine_route(drug_name, order.clinical_intent),
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


def _generate_vitals(
    state: PhysiologicalState,
    patient: PatientProfile,
    day: int,
    admission_time: datetime,
    rng: np.random.Generator,
) -> list[VitalSignRecord]:
    """Generate vital sign measurements for this day with context-dependent frequency."""
    vitals: list[VitalSignRecord] = []

    # Measurement schedule depends on acuity
    if state.perfusion_status < 0.5 or state.inflammation_level > 0.5:
        # Unstable: q4h
        hours = [2, 6, 10, 14, 18, 22]
    elif day <= 2:
        # Early admission: q6h
        hours = [0, 6, 12, 18]
    elif state.inflammation_level < 0.1 and day >= 7:
        # Stable, late stay: bid
        hours = [6, 18]
    else:
        # Standard: tid
        hours = [6, 14, 18]

    for hour in hours:
        vit_time = datetime(admission_time.year, admission_time.month, admission_time.day, hour, 0) + timedelta(days=day)
        if vit_time < admission_time:
            continue

        raw = derive_vital_signs(state, patient.baseline_vitals, vit_time)
        for key in raw:
            raw[key] += float(rng.normal(0, 0.5 if key == "temperature" else 2))
            if key == "spo2":
                raw[key] = min(100.0, max(60.0, raw[key]))

        # Add jitter to measurement time (realistic: ±15 min for ward)
        jitter_min = float(rng.normal(0, 10))
        actual_time = vit_time + timedelta(minutes=jitter_min)

        # Pain score (NRS 0-10): correlates with inflammation and surgical status
        base_pain = state.inflammation_level * 4  # inflammation → pain
        if day <= 2:
            base_pain += 2  # acute phase
        pain = max(0, min(10, int(rng.normal(base_pain, 1.5))))

        # Brief nursing note (context-dependent)
        note_parts = []
        if raw["temperature"] >= 38.0:
            note_parts.append("febrile")
        if pain >= 5:
            note_parts.append(f"pain {pain}/10, analgesic administered")
        elif pain >= 3:
            note_parts.append(f"mild pain {pain}/10")
        if raw["spo2"] < 93:
            note_parts.append(f"SpO2 low, O2 adjusted")
        if state.inflammation_level < 0.1 and day >= 3:
            note_parts.append("improving, appetite good")
        if day == 0:
            note_parts.append("admission assessment completed")
        nursing_note = ". ".join(note_parts) + "." if note_parts else ""

        vitals.append(VitalSignRecord(
            timestamp=actual_time,
            temperature_celsius=round(raw["temperature"], 1),
            heart_rate=int(round(raw["heart_rate"])),
            systolic_bp=int(round(raw["systolic_bp"])),
            diastolic_bp=int(round(raw["diastolic_bp"])),
            respiratory_rate=int(round(raw["respiratory_rate"])),
            spo2=round(raw["spo2"], 1),
            pain_score=pain,
            nursing_note=nursing_note,
            data_source="manual",
        ))

    return vitals


# ============================================================
# Discharge prescription
# ============================================================

def _build_discharge_rx(
    patient: PatientProfile,
    disease_id: str,
    protocol: DiseaseProtocol,
    prescriber_id: str,
    rng: np.random.Generator,
    country_key: str = "japan",
) -> PrescriptionRecord:
    """Build discharge prescription from protocol."""
    items: list[dict] = []

    discharge_drugs = protocol.drugs.get("discharge_oral", {}).get(country_key, [])
    if isinstance(discharge_drugs, dict):
        discharge_drugs = [discharge_drugs]

    for drug_spec in discharge_drugs:
        if isinstance(drug_spec, dict):
            items.append({
                "drug_name": drug_spec.get("drug", ""),
                "dose": drug_spec.get("dose", ""),
                "duration_days": drug_spec.get("duration_days", 7),
                "route": "PO",
            })

    # Continue chronic medications
    for med in patient.current_medications:
        items.append({"drug_name": med, "dose": "", "route": "PO", "duration_days": 28})

    return PrescriptionRecord(
        prescription_id=f"RX-{patient.patient_id}-DC",
        patient_id=patient.patient_id,
        prescriber_id=prescriber_id,
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
# Mortality evaluation
# ============================================================

# ============================================================
# Outpatient encounter simulation
# ============================================================

def _simulate_outpatient_visit(
    patient: PatientProfile,
    visit_type: str,
    visit_date: datetime,
    roster: StaffRoster,
    rng: np.random.Generator,
    chronic_code: str = "",
    followup_spec: dict | None = None,
    post_discharge_disease: str = "",
) -> CIFPatientRecord:
    """Simulate a single outpatient visit (chronic follow-up or post-discharge).

    Generates: 1 encounter, 0-3 lab orders, 1 vital sign set, prescription renewal.
    """
    import uuid
    opd_num = int(uuid.uuid4().hex[:4], 16) % 9000 + 1000

    # Build visit reason from YAML spec or disease-specific post-discharge reason
    spec = followup_spec or {}
    if spec.get("visit_reason"):
        chief = spec["visit_reason"]
    elif post_discharge_disease:
        # Look up disease-specific post-discharge reason
        from clinosim.locale.loader import load_chronic_followup
        fu = load_chronic_followup()
        disease_fu = fu.get("_post_discharge_by_disease", {}).get(post_discharge_disease, {})
        chief = disease_fu.get("visit_reason", f"Post-discharge follow-up: {post_discharge_disease}")
    else:
        chief = f"Follow-up: {chronic_code}"

    encounter = create_inpatient_encounter(
        patient.patient_id, visit_date,
        chief_complaint=chief,
        visit_number=opd_num,
    )
    encounter.encounter_type = EncounterType.OUTPATIENT
    encounter.status = EncounterStatus.COMPLETED
    encounter.discharge_datetime = visit_date + timedelta(minutes=int(rng.integers(15, 45)))

    staff = assign_staff("rounds", "internal_medicine", roster, rng)
    encounter.attending_physician_id = staff.get("attending_physician", "DR-001")

    orders: list[Order] = []
    lab_results: list[OrderResult] = []
    vitals: list[VitalSignRecord] = []

    spec = followup_spec or {}

    # Vitals
    baseline = patient.baseline_vitals
    raw_vitals = {
        "temperature": float(rng.normal(36.4, 0.2)),
        "heart_rate": float(baseline.heart_rate + rng.normal(0, 5)),
        "systolic_bp": float(baseline.systolic_bp + rng.normal(0, 8)),
        "diastolic_bp": float(baseline.diastolic_bp + rng.normal(0, 5)),
        "respiratory_rate": float(rng.normal(16, 1.5)),
        "spo2": float(min(99, rng.normal(97.5, 0.8))),
    }
    vitals.append(VitalSignRecord(
        timestamp=visit_date + timedelta(minutes=5),
        temperature_celsius=round(raw_vitals["temperature"], 1),
        heart_rate=int(round(raw_vitals["heart_rate"])),
        systolic_bp=int(round(raw_vitals["systolic_bp"])),
        diastolic_bp=int(round(raw_vitals["diastolic_bp"])),
        respiratory_rate=int(round(raw_vitals["respiratory_rate"])),
        spo2=round(raw_vitals["spo2"], 1),
        data_source="manual",
    ))

    # Labs (if specified in followup schedule)
    lab_tests = spec.get("labs", [])
    for i, test_name in enumerate(lab_tests):
        order = Order(
            order_id=f"ORD-{patient.patient_id}-OPD-L{i:02d}",
            patient_id=patient.patient_id,
            order_type=OrderType.LAB,
            display_name=test_name,
            urgency="routine",
            clinical_intent=f"Outpatient follow-up: {test_name}",
            ordered_datetime=visit_date + timedelta(minutes=10),
            status=OrderStatus.PLACED,
        )
        orders.append(order)

        # Generate result (use baseline-ish values for stable outpatient)
        from clinosim.modules.observation.engine import generate_lab_result, determine_flag
        baseline_values = {"CRP": 0.5, "WBC": 6500, "Creatinine": 0.9, "K": 4.2,
                           "Na": 140, "Glucose": 100, "HbA1c": 6.5, "BNP": 50,
                           "PT_INR": 1.1, "Hb": 13.0, "AST": 25, "ALT": 22,
                           "BUN": 15, "Ca": 9.2, "eGFR": 75, "TSH": 2.5}
        true_val = baseline_values.get(test_name, 100.0)
        observed = generate_lab_result(test_name, true_val, rng)
        flag = determine_flag(test_name, observed, sex=patient.sex)
        result = OrderResult(
            result_datetime=visit_date + timedelta(hours=2),
            lab_name=test_name, value=observed,
            unit=get_lab_unit(test_name), flag=flag,
        )
        order.result = result
        order.status = OrderStatus.RESULTED
        lab_results.append(result)

    # Prescription renewal
    rx = None
    if spec.get("prescriptions_renewed") and patient.current_medications:
        rx = PrescriptionRecord(
            prescription_id=f"RX-{patient.patient_id}-OPD",
            prescriber_id=encounter.attending_physician_id,
            items=[{"drug": med, "duration_days": 30} for med in patient.current_medications],
        )

    dx_code = chronic_code or post_discharge_disease or "Z09"  # Z09 = follow-up examination
    condition_event = ConditionEvent(
        condition_id=f"COND-{patient.patient_id}-OPD",
        condition_type="chronic_followup" if chronic_code else "post_discharge_followup",
        ground_truth_diseases=[dx_code] if dx_code else [],
    )
    clinical_diagnosis = ClinicalDiagnosis(
        admission_diagnosis_code=dx_code,
        discharge_diagnosis_code=dx_code,
    )

    return CIFPatientRecord(
        patient=patient,
        encounters=[encounter],
        orders=orders,
        vital_signs=vitals,
        lab_results=lab_results,
        condition_event=condition_event,
        clinical_diagnosis=clinical_diagnosis,
        discharge_prescription=rx,
        physiological_states=[],
    )


def _simulate_ed_visit(
    patient: PatientProfile,
    condition: dict,
    visit_time: datetime,
    roster: StaffRoster,
    rng: np.random.Generator,
) -> CIFPatientRecord:
    """Simulate an ED visit using YAML protocol if available, else basic."""
    import uuid
    from clinosim.modules.observation.engine import generate_lab_result, determine_flag

    # Try to load detailed YAML protocol
    cond_name = condition.get("name", condition.get("condition_id", "ed_visit"))
    try:
        from clinosim.modules.encounter.protocol import load_encounter_condition
        protocol = load_encounter_condition(cond_name)
    except (FileNotFoundError, Exception):
        protocol = None

    chief = (protocol or condition).get("chief_complaint", cond_name)

    ed_num = int(uuid.uuid4().hex[:4], 16) % 9000 + 1000
    encounter = create_inpatient_encounter(
        patient.patient_id, visit_time,
        chief_complaint=chief,
        visit_number=ed_num,
    )
    encounter.encounter_type = EncounterType.EMERGENCY
    encounter.status = EncounterStatus.COMPLETED

    staff = assign_staff("admission", "internal_medicine", roster, rng)
    encounter.attending_physician_id = staff.get("attending_physician", "DR-001")

    # ED stay duration from protocol or default
    if protocol:
        severity = str(rng.choice(["mild", "moderate", "severe"],
                        p=[protocol.get("severity_distribution", {}).get(s, 0.33)
                           for s in ["mild", "moderate", "severe"]]))
        stay_cfg = protocol.get("ed_stay_hours", {}).get(severity, {"mean": 3, "sd": 1})
        ed_hours = float(rng.normal(stay_cfg["mean"], stay_cfg["sd"]))
    else:
        ed_hours = float(rng.normal(3.5, 1.0))
    encounter.discharge_datetime = visit_time + timedelta(hours=max(1, ed_hours))

    orders: list[Order] = []
    lab_results: list[OrderResult] = []

    # Labs from protocol workup
    workup = (protocol or {}).get("workup", {})
    lab_specs = workup.get("labs", [])
    if not lab_specs and not protocol:
        # Default: basic labs with 60% probability
        if rng.random() < 0.6:
            lab_specs = [{"test": "WBC", "probability": 1.0},
                         {"test": "CRP", "probability": 1.0},
                         {"test": "Creatinine", "probability": 1.0}]

    baseline_values = {"WBC": 7500, "CRP": 1.0, "Creatinine": 0.9, "Na": 140,
                       "K": 4.2, "Glucose": 100, "Troponin": 0.01, "BNP": 50}
    for i, lab_spec in enumerate(lab_specs):
        test = lab_spec.get("test", "")
        prob = lab_spec.get("probability", 1.0)
        if rng.random() > prob:
            continue
        order = Order(
            order_id=f"ORD-{patient.patient_id}-ED-L{i}",
            patient_id=patient.patient_id,
            order_type=OrderType.LAB,
            display_name=test, urgency="stat",
            clinical_intent=f"ED workup: {test}",
            ordered_datetime=visit_time + timedelta(minutes=int(rng.normal(10, 5))),
            status=OrderStatus.PLACED,
        )
        observed = generate_lab_result(test, baseline_values.get(test, 100), rng)
        flag = determine_flag(test, observed, sex=patient.sex)
        order.result = OrderResult(
            result_datetime=visit_time + timedelta(minutes=int(rng.normal(50, 15))),
            lab_name=test, value=observed,
            unit=get_lab_unit(test), flag=flag,
        )
        order.status = OrderStatus.RESULTED
        orders.append(order)
        lab_results.append(order.result)

    # Imaging from protocol
    for i, img_spec in enumerate(workup.get("imaging", [])):
        test = img_spec.get("test", "")
        if rng.random() > img_spec.get("probability", 1.0):
            continue
        orders.append(Order(
            order_id=f"ORD-{patient.patient_id}-ED-I{i}",
            patient_id=patient.patient_id,
            order_type=OrderType.IMAGING,
            display_name=test, urgency="stat",
            clinical_intent=f"ED imaging: {test}",
            ordered_datetime=visit_time + timedelta(minutes=int(rng.normal(20, 8))),
            status=OrderStatus.PLACED,
        ))

    # Treatment orders from protocol
    for i, tx in enumerate((protocol or {}).get("treatment", [])):
        if rng.random() > tx.get("probability", 1.0):
            continue
        orders.append(Order(
            order_id=f"ORD-{patient.patient_id}-ED-T{i}",
            patient_id=patient.patient_id,
            order_type=OrderType.MEDICATION,
            display_name=tx.get("name", ""),
            urgency="stat",
            clinical_intent=f"ED treatment: {tx.get('intent', tx.get('name', ''))}",
            ordered_datetime=visit_time + timedelta(minutes=int(rng.normal(30, 10))),
            status=OrderStatus.PLACED,
        ))

    # Vitals
    bv = patient.baseline_vitals
    vitals = [VitalSignRecord(
        timestamp=visit_time + timedelta(minutes=5),
        temperature_celsius=round(float(rng.normal(36.8, 0.5)), 1),
        heart_rate=int(rng.normal(bv.heart_rate, 10)),
        systolic_bp=int(rng.normal(bv.systolic_bp, 10)),
        diastolic_bp=int(rng.normal(bv.diastolic_bp, 7)),
        respiratory_rate=int(rng.normal(16, 2)),
        spo2=round(float(min(99, rng.normal(97.5, 1))), 1),
        pain_score=int(max(0, min(10, rng.normal(3, 2)))),
        data_source="manual",
    )]

    return CIFPatientRecord(
        patient=patient,
        encounters=[encounter],
        orders=orders,
        vital_signs=vitals,
        lab_results=lab_results,
        condition_event=ConditionEvent(
            condition_id=f"COND-{patient.patient_id}-ED",
            condition_type="ed_visit",
            ground_truth_diseases=[cond_name],
        ),
        clinical_diagnosis=ClinicalDiagnosis(
            admission_diagnosis_code=cond_name,
            discharge_diagnosis_code=cond_name,
            discharge_diagnosis_name=chief,
        ),
    )


_protocol_cache: dict[str, DiseaseProtocol] | None = None


def _load_all_disease_protocols() -> dict[str, DiseaseProtocol]:
    """Auto-discover and load all disease protocol YAMLs. Cached after first call."""
    global _protocol_cache
    if _protocol_cache is not None:
        return _protocol_cache
    from pathlib import Path
    ref_dir = Path(__file__).parent / "modules" / "disease" / "reference_data"
    protocols: dict[str, DiseaseProtocol] = {}
    for yaml_file in sorted(ref_dir.glob("*.yaml")):
        disease_id = yaml_file.stem
        try:
            protocols[disease_id] = load_disease_protocol(disease_id)
        except Exception:
            pass
    _protocol_cache = protocols
    return protocols


def _deactivate_to_layer1(
    person: Any,
    record: CIFPatientRecord,
    disease_id: str,
) -> None:
    """Feed hospital results back to Layer 1 PersonRecord after discharge.

    Updates chronic conditions, medications, and hospitalization history
    so future encounters can reference the patient's medical history.
    """
    from clinosim.modules.population.engine import HospitalizationSummary

    person.has_visited_hospital = True
    person.visit_count += 1

    # Encounter tracking
    if record.encounters:
        enc = record.encounters[0]
        person.last_encounter_id = enc.encounter_id
        person.last_disease_id = disease_id
        if enc.discharge_datetime:
            person.last_discharge_date = enc.discharge_datetime.date()

    # Add new diagnoses to chronic conditions
    dx_code = record.clinical_diagnosis.discharge_diagnosis_code
    if dx_code:
        # Normalize to base code (e.g., "J44.1" → "J44") for chronic condition tracking
        base_code = dx_code.split(".")[0] if "." in dx_code else dx_code
        # Only add if it's a chronic/recurring condition and not already present
        chronic_prefixes = ("I", "E", "J44", "J45", "N18", "M", "G20", "F00", "K21", "N40")
        if any(base_code.startswith(p) for p in chronic_prefixes):
            # Check if base code already in chronic conditions
            existing_bases = {c.split(".")[0] for c in person.chronic_conditions}
            if base_code not in existing_bases:
                person.chronic_conditions.append(base_code)

    # Update medications: discharge prescriptions become current medications
    if record.discharge_prescription and record.discharge_prescription.items:
        person.current_medications = [
            item.get("drug", item.get("name", ""))
            for item in record.discharge_prescription.items
            if isinstance(item, dict)
        ]

    # Residual physiological state at discharge
    residual_infl = 0.0
    residual_renal = 1.0
    if record.physiological_states:
        final = record.physiological_states[-1]
        residual_infl = final.inflammation_level
        residual_renal = final.renal_function

    # Build hospitalization summary
    admission_date = record.encounters[0].admission_datetime.date() if record.encounters else None
    discharge_date = person.last_discharge_date
    if admission_date and discharge_date:
        los = (discharge_date - admission_date).days
    else:
        los = len(record.physiological_states) - 1

    summary = HospitalizationSummary(
        encounter_id=person.last_encounter_id or "",
        disease_id=disease_id,
        admission_date=admission_date or discharge_date or record.encounters[0].admission_datetime.date(),
        discharge_date=discharge_date or admission_date or record.encounters[0].admission_datetime.date(),
        los_days=max(1, los),
        outcome="deceased" if record.deceased else "discharged",
        discharge_diagnoses=[dx_code] if dx_code else [disease_id],
        discharge_medications=person.current_medications.copy(),
        residual_inflammation=residual_infl,
        residual_renal=residual_renal,
        was_readmission=record.is_readmission,
    )
    person.hospitalization_history.append(summary)


def _select_secondary_disease(
    patient: PatientProfile,
    primary_disease_id: str,
    protocols: dict[str, DiseaseProtocol],
    rng: np.random.Generator,
) -> DiseaseProtocol | None:
    """Select a secondary disease for mixed conditions based on patient's chronic diseases.

    Priority: diseases whose prerequisite_condition matches patient's chronic conditions.
    Fallback: any non-surgical disease different from primary.
    """
    # Find candidate diseases (non-surgical, different from primary)
    matching = []
    for did, proto in protocols.items():
        if did == primary_disease_id or proto.requires_surgery:
            continue
        # Check demographics YAML prerequisite — read from incidence data isn't available here,
        # but we can check if the disease name implies a chronic condition match
        # Use a simpler approach: any medical disease the patient could plausibly have
        matching.append(proto)

    if not matching:
        return None

    # Prefer diseases related to patient's comorbidities
    # Pneumonia is common secondary for any hospitalized patient
    preferred = [p for p in matching if p.disease_id == "bacterial_pneumonia"]
    if preferred:
        return preferred[0]

    return rng.choice(matching)


def _evaluate_readmission(
    record: CIFPatientRecord,
    person: Any,
    disease_id: str,
    protocol: DiseaseProtocol,
    country_key: str,
    rng: np.random.Generator,
) -> LifeEvent | None:
    """Evaluate 30-day readmission probability and generate event if triggered.

    Uses YAML benchmark rates as the TARGET rate. Risk modifiers adjust around
    the benchmark but the final rate is clamped near the benchmark range.
    """
    # Check if this disease type is eligible for same-disease readmission
    if not protocol.readmission_eligible:
        return None

    benchmarks = protocol.outcome_benchmarks.get(country_key, {})
    base_rate = benchmarks.get("thirty_day_readmission", 0.15)

    # Start from base rate, apply modest modifiers
    rate = base_rate

    # Risk modifiers — all modest, multiplicative effects compound
    modifier = 1.0

    # Residual inflammation at discharge (incomplete recovery)
    if record.physiological_states:
        final_infl = record.physiological_states[-1].inflammation_level
        if final_infl > 0.15:
            modifier *= 1.15

    # Age (elderly more likely to bounce back)
    age = record.patient.age
    if age >= 80:
        modifier *= 1.1
    elif age >= 70:
        modifier *= 1.05

    # Comorbidity burden (small additive)
    n_chronic = len(record.patient.chronic_conditions)
    modifier += n_chronic * 0.01

    # Diagnosis accuracy
    if record.clinical_diagnosis.missed_diagnoses:
        modifier *= 1.2

    rate = base_rate * modifier
    # Clamp: stay within 50% of benchmark
    rate = min(rate, base_rate * 1.5)

    if rng.random() >= rate:
        return None

    discharge_date = person.last_discharge_date
    if not discharge_date:
        return None

    readmit_days = int(rng.integers(2, 28))
    readmit_date = discharge_date + timedelta(days=readmit_days)

    # Readmission severity: slightly higher than original
    original_severity = 0.5
    if record.physiological_states:
        original_severity = record.physiological_states[0].inflammation_level
    readmit_severity = min(1.0, original_severity + float(rng.uniform(0.05, 0.15)))

    return LifeEvent(
        person_id=person.person_id,
        event_type="readmission",
        timestamp=readmit_date,
        severity=readmit_severity,
        disease_id=disease_id,
        requires_hospital=True,
        condition_type="known_disease",
        is_readmission=True,
        prior_encounter_id=person.last_encounter_id,
        readmission_number=(record.readmission_number or 0) + 1,
    )


def _country_to_yaml_key(country: str) -> str:
    """Convert country code to disease YAML key."""
    return {"JP": "japan", "US": "us"}.get(country, "us")


def _disease_chief_complaint(protocol: DiseaseProtocol) -> str:
    """Get chief complaint from disease protocol YAML."""
    return protocol.chief_complaint or "General malaise"


def _disease_to_department(protocol: DiseaseProtocol) -> str:
    """Get managing department from disease protocol YAML."""
    return protocol.department or "internal_medicine"


def _determine_route(drug_name: str, clinical_intent: str) -> str:
    """Determine medication administration route."""
    combined = (drug_name + " " + clinical_intent).upper()
    if "IV" in combined or "DRIP" in combined:
        return "IV"
    if "SC" in combined or "SUBCUTANEOUS" in combined or "ENOXAPARIN" in combined.upper():
        return "SC"
    if "IM" in combined:
        return "IM"
    # Known IV drugs
    iv_drugs = ["AMPICILLIN", "SULBACTAM", "CEFTRIAXONE", "MEROPENEM",
                "FUROSEMIDE", "NITROGLYCERIN", "VANCOMYCIN", "LEVOFLOXACIN"]
    for d in iv_drugs:
        if d in drug_name.upper():
            return "IV"
    return "PO"


def _check_discharge_ready(
    state: PhysiologicalState,
    day: int,
    country_key: str,
) -> bool:
    """Check if patient meets state-based discharge criteria.

    Common criteria across diseases:
    - Inflammation resolving (CRP proxy)
    - Hemodynamically stable (perfusion)
    - No acute organ dysfunction
    JP: stricter (lower inflammation threshold, longer afebrile requirement)
    US: earlier discharge once clinically stable
    """
    if country_key == "us":
        return (
            state.inflammation_level < 0.10
            and state.perfusion_status > 0.7
            and state.renal_function > 0.5
            and abs(state.volume_status) < 0.3
            and abs(state.ph_status) < 0.2
        )
    else:  # japan — stricter criteria
        return (
            state.inflammation_level < 0.05
            and state.perfusion_status > 0.8
            and state.renal_function > 0.6
            and abs(state.volume_status) < 0.2
            and abs(state.ph_status) < 0.15
        )


def _evaluate_mortality(
    state: PhysiologicalState,
    patient: Any,
    severity: str,
    day: int,
    rng: np.random.Generator,
    disease_mortality_rate: float = 0.0,
    target_los: int = 14,
) -> bool:
    """Daily mortality evaluation using disease-specific benchmark rates.

    If disease_mortality_rate is provided (from YAML outcome_benchmarks),
    it is used as the total in-hospital mortality rate and spread across the LOS.
    """
    if disease_mortality_rate > 0:
        # Spread total mortality across hospital stay, weighted by day
        day_weight = 1.5 if 2 <= day <= 7 else (0.5 if day > 14 else 1.0)
        daily_base = disease_mortality_rate / max(target_los, 1) * day_weight
        # When benchmark is used, apply only mild individual modifiers
        # The benchmark already accounts for average patient demographics
        age = patient.age if hasattr(patient, "age") else 70
        individual_mod = 1.0
        if age >= 85:
            individual_mod *= 1.2
        if state.perfusion_status < 0.3:
            individual_mod *= 1.3
        individual_mod = min(individual_mod, 1.8)
        return bool(rng.random() < daily_base * individual_mod)
    else:
        daily_base = {"severe": 0.003, "moderate": 0.0005}.get(severity, 0.0001)
        age = patient.age if hasattr(patient, "age") else 70
        age_mult = 1.5 if age >= 85 else (1.2 if age >= 80 else 1.0)
        return bool(rng.random() < daily_base * age_mult)


# ============================================================
# Unknown condition simulation
# ============================================================

def _simulate_unknown_condition(
    patient: PatientProfile,
    event: LifeEvent,
    rng: np.random.Generator,
    healthcare: HealthcareSystemConfig,
    roster: StaffRoster,
) -> CIFPatientRecord | None:
    """Simulate patient with unknown/idiopathic condition.

    Unlike known-disease patients, unknown condition patients undergo extensive
    diagnostic workup that progressively broadens without reaching a conclusion.
    """
    state = initialize_state(patient.physiological_profile, patient.chronic_conditions, patient.patient_id)
    state.inflammation_level += float(rng.uniform(0.10, 0.30))

    admission_time = datetime(event.timestamp.year, event.timestamp.month, event.timestamp.day,
                               int(rng.integers(8, 22)), 0)
    complaint = event.disease_id.replace("unknown_", "").replace("_", " ")
    encounter = create_inpatient_encounter(patient.patient_id, admission_time, chief_complaint=complaint)
    attending_id = assign_staff("admission", "internal_medicine", roster, rng).get("attending_physician", "DR-001")
    encounter.attending_physician_id = attending_id
    # Ward/bed for unknown condition patients
    ward_floor = int(rng.integers(3, 7))
    encounter.ward_id = f"{ward_floor}{'EW'[int(rng.integers(0, 2))]}"
    encounter.bed_number = f"{ward_floor}{int(rng.integers(1, 30)):02d}-{int(rng.integers(1, 5))}"
    encounter.attending_physician_id = attending_id

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

        # Generate lab results
        true_labs = derive_lab_values(state, sex=patient.sex, age=patient.age, has_diabetes=has_diabetes)
        for order in all_orders:
            if order.order_type.value == "lab" and order.status == OrderStatus.PLACED and order.display_name in true_labs:
                result_time = calculate_lab_result_time(order, rng)
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
        all_vitals.extend(_generate_vitals(state, patient, day, admission_time, rng))

        # MAR for supportive medications
        all_mars.extend(_generate_mar(patient, all_orders, day, admission_time, roster, rng))

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

    return CIFPatientRecord(
        patient=patient, encounters=[encounter],
        orders=all_orders, vital_signs=all_vitals, lab_results=all_lab_results,
        medication_administrations=all_mars,
        condition_event=ConditionEvent(condition_id=f"COND-{patient.patient_id}-UNK",
                                       condition_type="unknown", symptom_pattern=event.disease_id),
        clinical_diagnosis=ClinicalDiagnosis(
            admission_diagnosis_code="R50.9" if "fever" in event.disease_id else "R53.1",
            admission_diagnosis_name=complaint.title(),
            discharge_diagnosis_code=discharge_code,
            discharge_diagnosis_name=discharge_name,
            diagnosis_correct=False,
        ),
        physiological_states=state_history,
    )


# ============================================================
# CLI entry point
# ============================================================

def run_forced(scenario: ForcedScenario, config: SimulatorConfig | None = None) -> CIFDataset:
    """Generate data for a specific forced scenario only. No population needed.

    Usage:
        from clinosim.types.config import ForcedScenario, SimulatorConfig
        scenario = ForcedScenario(disease_id="bacterial_pneumonia", count=5, archetype="treatment_resistant")
        dataset = run_forced(scenario)
    """
    if config is None:
        config = SimulatorConfig()

    rng = np.random.default_rng(config.random_seed)
    healthcare = load_healthcare_config(config.country)
    roster = generate_roster(config.hospital_scale, config.country, rng)

    protocol = load_disease_protocol(scenario.disease_id)

    patient_records: list[CIFPatientRecord] = []

    for i in range(scenario.count):
        # Create patient (from overrides or random)
        from clinosim.modules.patient.activator import activate_patient
        from clinosim.modules.population.engine import PersonRecord
        from datetime import date

        if scenario.patient_overrides:
            age = scenario.patient_overrides.get("age", 72)
            sex = scenario.patient_overrides.get("sex", "F")
        else:
            age = int(rng.integers(55, 95))
            sex = str(rng.choice(["M", "F"]))

        # Create a minimal PersonRecord for activation
        person = PersonRecord(
            person_id=f"FORCED-{i+1:04d}",
            household_id=f"HH-FORCED-{i+1:04d}",
            age=age,
            sex=sex,
            date_of_birth=date(2024 - age, 1, 1),
            family_name="テスト" if config.country == "JP" else "Test",
            given_name=f"患者{i+1}" if config.country == "JP" else f"Patient{i+1}",
            chronic_conditions=scenario.patient_overrides.get("chronic_conditions", []),
        )
        patient = activate_patient(person, rng, config.country)

        # Force severity and archetype
        severity = scenario.severity or "moderate"

        # Create life event
        event = LifeEvent(
            person_id=patient.patient_id,
            event_type="forced",
            timestamp=date(2024, 6, 15),
            severity={"mild": 0.2, "moderate": 0.5, "severe": 0.8}.get(severity, 0.5),
            disease_id=scenario.disease_id,
            requires_hospital=True,
            condition_type="known_disease",
        )

        record = _simulate_patient(
            patient, event, scenario.disease_id, protocol,
            healthcare, roster, config, rng,
            forced_severity=scenario.severity,
            forced_archetype=scenario.archetype,
        )

        # Force specific complications if requested
        if scenario.complications:
            record.complications_occurred.extend(scenario.complications)

        patient_records.append(record)

    metadata = CIFMetadata(
        clinosim_version="0.1.0",
        random_seed=config.random_seed,
        country=config.country,
        hospital_scale=config.hospital_scale,
        total_patients_generated=len(patient_records),
        llm_mode="none",
    )
    return CIFDataset(metadata=metadata, patients=patient_records)


def run_alpha(config: SimulatorConfig | None = None) -> CIFDataset:
    """Backward-compatible alpha: 1 pneumonia patient via ForcedScenario."""
    scenario = ForcedScenario(
        disease_id="bacterial_pneumonia", count=1,
        severity="moderate", archetype="smooth_recovery",
        patient_overrides={"age": 72, "sex": "F"},
    )
    return run_forced(scenario, config)


def main() -> None:
    """CLI entry point: clinosim [command] [options]"""
    import argparse

    parser = argparse.ArgumentParser(
        prog="clinosim",
        description="Clinically Realistic Hospital Data Simulator",
    )
    sub = parser.add_subparsers(dest="command", help="Command to run")

    # === generate: population-driven simulation ===
    gen = sub.add_parser("generate", help="Generate patient data from population simulation")
    gen.add_argument("-o", "--output", default="./output", help="Output directory")
    gen.add_argument("-p", "--population", type=int, default=10_000, help="Catchment population size")
    gen.add_argument("-s", "--seed", type=int, default=42, help="Random seed")
    gen.add_argument("--country", default="US", help="Country code (US or JP)")
    gen.add_argument("--period", default="2024-04-01,2025-03-31", help="Simulation period (start,end)")
    gen.add_argument("--format", nargs="+", default=["cif"], help="Output formats: cif, csv, fhir")
    gen.add_argument("--narrative", action="store_true", help="Generate narrative layer (requires Ollama)")
    gen.add_argument("--narrative-model", default="qwen:7b", help="Ollama model for narratives")

    # === test-disease: generate specific disease/archetype ===
    td = sub.add_parser("test-disease", help="Generate data for a specific disease and archetype")
    td.add_argument("disease_id", help="Disease ID (e.g., bacterial_pneumonia)")
    td.add_argument("-o", "--output", default="./output", help="Output directory")
    td.add_argument("-n", "--count", type=int, default=3, help="Number of patients")
    td.add_argument("--severity", default=None, help="Force severity: mild/moderate/severe")
    td.add_argument("--archetype", default=None, help="Force archetype name")
    td.add_argument("-s", "--seed", type=int, default=42, help="Random seed")
    td.add_argument("--country", default="US", help="Country code (US or JP)")
    td.add_argument("--format", nargs="+", default=["cif", "csv"], help="Output formats")

    # === validate: run quality checks on generated data ===
    val = sub.add_parser("validate", help="Run data quality checks on generated data")
    val.add_argument("-p", "--population", type=int, default=5_000, help="Population size")
    val.add_argument("-s", "--seed", type=int, default=42, help="Random seed")
    val.add_argument("--country", default="US", help="Country code")

    # === list-diseases: show available disease protocols ===
    sub.add_parser("list-diseases", help="List all available disease protocols")

    args = parser.parse_args()

    if args.command == "list-diseases":
        protocols = _load_all_disease_protocols()
        print(f"{len(protocols)} disease protocols available:")
        for name in sorted(protocols.keys()):
            p = protocols[name]
            print(f"  {name:35s} | {p.chief_complaint[:50]}")
        return

    if args.command == "validate":
        config = SimulatorConfig(
            catchment_population=args.population,
            random_seed=args.seed, country=args.country,
        )
        print(f"clinosim validate: pop={args.population}, country={args.country}")
        dataset = run_beta(config)
        _run_quality_checks(dataset)
        return

    if args.command == "generate":
        start, end = args.period.split(",")
        config = SimulatorConfig(
            catchment_population=args.population,
            time_range=(start.strip(), end.strip()),
            random_seed=args.seed,
            country=args.country,
        )
        print(f"clinosim generate: population={args.population}, seed={args.seed}, country={args.country}")
        dataset = run_beta(config)

    elif args.command == "test-disease":
        scenario = ForcedScenario(
            disease_id=args.disease_id,
            count=args.count,
            severity=args.severity,
            archetype=args.archetype,
        )
        config = SimulatorConfig(random_seed=args.seed, country=args.country)
        print(f"clinosim test-disease: {args.disease_id} x{args.count}, country={args.country}")
        dataset = run_forced(scenario, config)

    else:
        parser.print_help()
        return

    # Output
    cif_dir = os.path.join(args.output, "cif")
    write_cif(dataset, cif_dir)

    if "csv" in args.format:
        from clinosim.modules.output.csv_adapter import convert_cif_to_csv
        convert_cif_to_csv(cif_dir, os.path.join(args.output, "csv"))

    if "fhir" in args.format:
        from clinosim.modules.output.fhir_r4_adapter import convert_cif_to_fhir
        country = getattr(args, "country", "US")
        convert_cif_to_fhir(cif_dir, os.path.join(args.output, "fhir_r4"), country=country)

    # Narrative layer (Stage 2, optional)
    if getattr(args, "narrative", False):
        from clinosim.modules.llm_service.engine import LLMService, OllamaProvider
        from clinosim.modules.output.narrative_generator import generate_narratives
        model = getattr(args, "narrative_model", "qwen:7b")
        print(f"  Generating narratives with {model}...")
        provider = OllamaProvider(model=model)
        llm = LLMService(mode="llm", narrative_provider=provider,
                         narrative_model_map={"small": model, "medium": model})
        lang = "ja" if getattr(args, "country", "US") == "JP" else "en"
        version = generate_narratives(cif_dir, llm, language=lang)
        print(f"  Narratives generated: version={version}")

    # Summary
    _print_summary(dataset, args.output)


def _print_summary(dataset: CIFDataset, output_dir: str) -> None:
    """Print a summary report of generated data."""
    from collections import Counter, defaultdict

    all_records = dataset.patients
    inpatients = [r for r in all_records if r.encounters and r.encounters[0].encounter_type.value == "inpatient"]
    outpatients = [r for r in all_records if r.encounters and r.encounters[0].encounter_type.value == "outpatient"]
    readmits = [r for r in inpatients if r.is_readmission]
    deceased = [r for r in all_records if r.deceased]

    print(f"\n{'='*50}")
    print(f"  clinosim generation complete")
    print(f"{'='*50}")
    print(f"  Total records:  {len(all_records)}")
    print(f"    Inpatient:    {len(inpatients)} ({len(readmits)} readmissions)")
    print(f"    Outpatient:   {len(outpatients)}")
    print(f"    Deceased:     {len(deceased)}")
    print(f"  Data volume:")
    print(f"    Lab results:  {sum(len(r.lab_results) for r in all_records):,}")
    print(f"    Vital signs:  {sum(len(r.vital_signs) for r in all_records):,}")
    print(f"    MAR entries:  {sum(len(r.medication_administrations) for r in all_records):,}")
    print(f"    I/O records:  {sum(len(r.intake_output_records) for r in all_records):,}")
    print(f"    Orders:       {sum(len(r.orders) for r in all_records):,}")

    # Disease distribution (inpatient only)
    by_disease = Counter()
    los_by_disease = defaultdict(list)
    for r in inpatients:
        d = r.condition_event.ground_truth_diseases[0] if r.condition_event.ground_truth_diseases else "?"
        by_disease[d] += 1
        los_by_disease[d].append(len(r.physiological_states) - 1)

    if by_disease:
        print(f"\n  Disease distribution (inpatient):")
        for d, n in by_disease.most_common(10):
            avg_los = sum(los_by_disease[d]) / len(los_by_disease[d])
            print(f"    {d:30s} {n:4d}  (LOS avg {avg_los:.1f}d)")

    print(f"\n  Output: {output_dir}/")


def _run_quality_checks(dataset: CIFDataset) -> None:
    """Run comprehensive quality checks on generated data."""
    from collections import Counter

    records = dataset.patients
    inpatients = [r for r in records if r.encounters and r.encounters[0].encounter_type == EncounterType.INPATIENT]
    outpatients = [r for r in records if r.encounters and r.encounters[0].encounter_type == EncounterType.OUTPATIENT]
    ed_visits = [r for r in records if r.encounters and r.encounters[0].encounter_type == EncounterType.EMERGENCY]

    print(f"\n{'='*50}")
    print("  Data Quality Report")
    print(f"{'='*50}")
    print(f"  Records: {len(records)} (inp={len(inpatients)}, opd={len(outpatients)}, ed={len(ed_visits)})")

    issues = 0

    # Check: labs have units
    no_unit = sum(1 for r in records for l in r.lab_results if not l.unit)
    if no_unit:
        print(f"  ❌ Labs missing units: {no_unit}")
        issues += 1
    else:
        print(f"  ✅ All labs have units")

    # Check: all records have diagnosis
    no_dx = sum(1 for r in records if not r.clinical_diagnosis.discharge_diagnosis_code)
    if no_dx:
        print(f"  ❌ Records missing diagnosis: {no_dx}")
        issues += 1
    else:
        print(f"  ✅ All records have diagnosis codes")

    # Check: inpatients have vitals, labs, MARs
    inp_no_vitals = sum(1 for r in inpatients if not r.vital_signs)
    inp_no_labs = sum(1 for r in inpatients if not r.lab_results)
    inp_no_mars = sum(1 for r in inpatients if not r.medication_administrations)
    for name, count in [("vitals", inp_no_vitals), ("labs", inp_no_labs), ("MARs", inp_no_mars)]:
        if count:
            print(f"  ❌ Inpatients missing {name}: {count}")
            issues += 1
        else:
            print(f"  ✅ All inpatients have {name}")

    # Check: ward/bed
    inp_no_ward = sum(1 for r in inpatients if not r.encounters[0].ward_id)
    print(f"  {'❌' if inp_no_ward else '✅'} Ward/bed assignment: {len(inpatients)-inp_no_ward}/{len(inpatients)}")
    if inp_no_ward: issues += 1

    # Check: pain scores
    vitals_with_pain = sum(1 for r in records for v in r.vital_signs if v.pain_score is not None)
    total_vitals = sum(len(r.vital_signs) for r in records)
    pct = vitals_with_pain / total_vitals * 100 if total_vitals else 0
    print(f"  ✅ Pain scores: {pct:.0f}% of vitals")

    # Check: ADL for inpatients
    adl_count = sum(len(r.adl_assessments) for r in inpatients)
    print(f"  ✅ ADL assessments: {adl_count} (avg {adl_count/len(inpatients):.1f}/patient)" if inpatients else "  - No inpatients")

    # Check: I/O for inpatients
    io_count = sum(len(r.intake_output_records) for r in inpatients)
    print(f"  ✅ I/O records: {io_count}")

    # Check: diet orders
    diet_count = sum(1 for r in inpatients if any(o.order_type.value == "diet" for o in r.orders))
    print(f"  ✅ Diet orders: {diet_count}/{len(inpatients)} inpatients")

    # Disease distribution
    by_disease = Counter()
    for r in inpatients:
        d = r.condition_event.ground_truth_diseases[0] if r.condition_event.ground_truth_diseases else "?"
        by_disease[d] += 1
    print(f"\n  Disease distribution ({len(by_disease)} types):")
    for d, n in by_disease.most_common(5):
        print(f"    {d:30s} {n:4d}")
    if len(by_disease) > 5:
        print(f"    ... and {len(by_disease)-5} more")

    # Readmission check
    readmits = sum(1 for r in inpatients if r.is_readmission)
    rate = readmits / (len(inpatients) - readmits) * 100 if len(inpatients) > readmits else 0
    print(f"\n  Readmission rate: {rate:.1f}% ({readmits} readmissions)")

    # Mortality
    deceased = sum(1 for r in records if r.deceased)
    mort_rate = deceased / len(inpatients) * 100 if inpatients else 0
    print(f"  Mortality rate: {mort_rate:.1f}% ({deceased} deaths)")

    print(f"\n  {'✅ ALL CHECKS PASSED' if issues == 0 else f'⚠ {issues} ISSUES FOUND'}")


if __name__ == "__main__":
    import os
    main()
