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
    evaluate_complications,
    get_daily_directive,
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
from clinosim.modules.observation.engine import determine_flag, generate_lab_result
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
    PopulationRegistry,
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
    StateChangeDirective,
)
from clinosim.types.config import ForcedScenario, HealthcareSystemConfig, SimulatorConfig
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
    protocols = {
        "bacterial_pneumonia": load_disease_protocol("bacterial_pneumonia"),
        "heart_failure_exacerbation": load_disease_protocol("heart_failure_exacerbation"),
        "hip_fracture": load_disease_protocol("hip_fracture"),
    }
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
        all_events.extend(generate_monthly_events(population, y, m, rng))
        m += 1
        if m > 12:
            m, y = 1, y + 1

    hospital_events = [e for e in all_events if e.requires_hospital]
    print(f"  Life events: {len(all_events)} total, {len(hospital_events)} requiring hospital")

    # Simulate each patient
    patient_records: list[CIFPatientRecord] = []
    for event in hospital_events:
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

        # Mixed condition: determine secondary disease and pass to simulator
        secondary_protocol = None
        if event.condition_type == "mixed":
            # Determine secondary disease based on patient's chronic conditions
            if "I50" in [c.code for c in patient.chronic_conditions] and disease_id != "heart_failure_exacerbation":
                secondary_protocol = protocols.get("heart_failure_exacerbation")
            elif disease_id == "heart_failure_exacerbation":
                secondary_protocol = protocols.get("bacterial_pneumonia")

        record = _simulate_patient(
            patient, event, disease_id, protocol, healthcare, roster, config, rng,
            secondary_protocol=secondary_protocol,
        )
        patient_records.append(record)
        person.has_visited_hospital = True
        person.visit_count += 1
        if record.deceased:
            person.is_alive = False

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
        if disease_id == "hip_fracture" and severity == "mild":
            severity = "moderate"

    if forced_archetype:
        archetype = forced_archetype
    else:
        archetype = select_archetype(severity, patient.physiological_profile, rng)

    # Initialize physiological state
    state = initialize_state(patient.physiological_profile, patient.chronic_conditions, patient.patient_id)
    state = apply_disease_onset(state, severity, protocol.initial_state_impact)

    # Mixed condition: superimpose secondary disease's state impact
    secondary_disease_id = None
    if secondary_protocol:
        secondary_disease_id = secondary_protocol.disease_id
        # Secondary disease typically presents at moderate severity
        state = apply_disease_onset(state, "moderate", secondary_protocol.initial_state_impact)

    # Create encounter
    admission_time = datetime(event.timestamp.year, event.timestamp.month, event.timestamp.day,
                               int(rng.integers(8, 22)), 0)
    encounter = create_inpatient_encounter(patient.patient_id, admission_time)

    # Staff assignment
    # Department assignment based on disease
    department = _disease_to_department(disease_id)
    staff = assign_staff("admission", department, roster, rng)
    attending_id = staff.get("attending_physician", "DR-001")
    encounter.attending_physician_id = attending_id

    # LOS
    los_cfg = protocol.target_los.get("japan", {}).get(severity, {"mean": 14, "sd": 4, "min": 5, "max": 30})
    target_los = int(max(los_cfg.get("min", 5), min(los_cfg.get("max", 30), rng.normal(los_cfg["mean"], los_cfg["sd"]))))

    # Admission orders
    admission_orders = place_admission_orders(
        protocol.model_dump(), patient.patient_id, encounter.encounter_id,
        admission_time, country="japan", rng=rng,
    )
    for o in admission_orders:
        o.ordered_by = attending_id

    # Tracking
    procedures, rehab_sessions = [], []
    icu_transferred, surgery_done, death_occurred = False, False, False

    # Surgery (hip fracture)
    if disease_id == "hip_fracture":
        proc, impacts = simulate_surgery(patient, disease_id, encounter.encounter_id,
                                          admission_time, protocol, rng, config.country)
        procedures.append(proc)
        surgery_done = True
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
    loop_result = _run_daily_loop(
        state, patient, disease_id, protocol, archetype, differential,
        admission_orders, admission_time, target_los, has_diabetes,
        healthcare, roster, rng,
    )

    # Unpack results
    all_orders = loop_result["orders"]
    all_lab_results = loop_result["lab_results"]
    all_vitals = loop_result["vitals"]
    all_mars = loop_result["mars"]
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
    discharge_rx = _build_discharge_rx(patient, disease_id, protocol, attending_id, rng) if not death_occurred else None

    # Encounter completion
    encounter.status = EncounterStatus.COMPLETED
    encounter.discharge_datetime = admission_time + timedelta(days=actual_los, hours=14 if not death_occurred else 0)

    return CIFPatientRecord(
        patient=patient, encounters=[encounter], orders=all_orders,
        vital_signs=all_vitals, lab_results=all_lab_results,
        condition_event=condition_event, clinical_diagnosis=clinical_diagnosis,
        complications_occurred=complications_occurred,
        procedures=procedures, rehab_sessions=rehab_sessions,
        medication_administrations=all_mars,
        discharge_prescription=discharge_rx,
        icu_transferred=icu_transferred, deceased=death_occurred,
        death_day=actual_los if death_occurred else None,
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
) -> dict:
    """Run the day-by-day simulation loop. Returns all generated data."""

    all_orders = list(admission_orders)
    all_lab_results: list[OrderResult] = []
    all_vitals: list[VitalSignRecord] = []
    all_mars: list[MedicationAdministration] = []
    state_history = [deepcopy(state)]
    active_complications: set[str] = set()
    complications_occurred: list[str] = []
    death_occurred = False
    icu_transferred = False
    treatment_changed = False

    for day in range(target_los):
        # State update
        directive = get_daily_directive(
            archetype, day, patient.physiological_profile,
            protocol_archetypes=protocol.course_archetypes or None,
            age=patient.age, rng=rng,
        )
        state = update(state, directive, timedelta(days=1))
        state_history.append(deepcopy(state))

        # Daily lab orders (from Day 1)
        if day >= 1:
            lab_time = datetime(admission_time.year, admission_time.month, admission_time.day, 6, 0) + timedelta(days=day)
            daily_orders = place_daily_lab_orders(
                protocol.model_dump(), patient.patient_id, "", day, lab_time,
                healthcare.lab_frequency_multiplier, rng,
            )
            all_orders.extend(daily_orders)

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
                result_time = calculate_lab_result_time(order, rng)
                observed = generate_lab_result(order.display_name, true_labs[order.display_name], rng)
                flag = determine_flag(order.display_name, observed, sex=patient.sex)
                lab_tech = assign_staff("lab_result", "", roster, rng).get("performing_technician", "TECH-001")
                order.result = OrderResult(
                    result_datetime=result_time, performed_by=lab_tech,
                    lab_name=order.display_name, value=observed, unit="", flag=flag,
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
            start_meds = mod.get("start", {}).get("japan", mod.get("start", []))
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
                        treatment_changed = True

        # Medication administration (MAR)
        mars_today = _generate_mar(patient, all_orders, day, admission_time, roster, rng)
        all_mars.extend(mars_today)

        # Vitals
        vitals_today = _generate_vitals(state, patient, day, admission_time, rng)
        all_vitals.extend(vitals_today)

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

        # Mortality
        if _evaluate_mortality(state, patient, severity="moderate", day=day, rng=rng):
            death_occurred = True
            break

    return {
        "orders": all_orders, "lab_results": all_lab_results, "vitals": all_vitals,
        "mars": all_mars, "state_history": state_history,
        "complications": complications_occurred, "death_occurred": death_occurred,
        "icu_transferred": icu_transferred, "differential": differential,
        "actual_los": day + 1 if death_occurred else target_los,
    }


# ============================================================
# Medication Administration Records (MAR)
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

def _generate_vitals(
    state: PhysiologicalState,
    patient: PatientProfile,
    day: int,
    admission_time: datetime,
    rng: np.random.Generator,
) -> list[VitalSignRecord]:
    """Generate vital sign measurements for this day."""
    vitals: list[VitalSignRecord] = []

    for hour in [6, 14, 18]:
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

        vitals.append(VitalSignRecord(
            timestamp=actual_time,
            temperature_celsius=round(raw["temperature"], 1),
            heart_rate=int(round(raw["heart_rate"])),
            systolic_bp=int(round(raw["systolic_bp"])),
            diastolic_bp=int(round(raw["diastolic_bp"])),
            respiratory_rate=int(round(raw["respiratory_rate"])),
            spo2=round(raw["spo2"], 1),
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
) -> PrescriptionRecord:
    """Build discharge prescription from protocol."""
    items: list[dict] = []

    discharge_drugs = protocol.drugs.get("discharge_oral", {}).get("japan", [])
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

def _disease_to_department(disease_id: str) -> str:
    """Map disease to the primary managing department."""
    mapping = {
        "bacterial_pneumonia": "internal_medicine",
        "heart_failure_exacerbation": "internal_medicine",  # cardiology in larger hospitals
        "hip_fracture": "internal_medicine",  # orthopedics for surgery, but internal med for medical management
        # In JP medium hospitals, orthopedics does surgery but internal medicine may manage medical issues
    }
    return mapping.get(disease_id, "internal_medicine")


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


def _evaluate_mortality(
    state: PhysiologicalState,
    patient: Any,
    severity: str,
    day: int,
    rng: np.random.Generator,
) -> bool:
    """Daily mortality evaluation."""
    base = {"severe": 0.003, "moderate": 0.0005}.get(severity, 0.0001)

    age = patient.age if hasattr(patient, "age") else 70
    age_mult = 3.0 if age >= 85 else (2.0 if age >= 80 else (1.5 if age >= 75 else 1.0))
    perf_mult = 5.0 if state.perfusion_status < 0.3 else (2.0 if state.perfusion_status < 0.5 else 1.0)
    renal_mult = 2.0 if state.renal_function < 0.2 else 1.0
    timing = 1.5 if 2 <= day <= 7 else (0.5 if day > 14 else 1.0)

    return bool(rng.random() < base * age_mult * perf_mult * renal_mult * timing)


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
                    lab_name=order.display_name, value=observed, unit="", flag=flag,
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
        from clinosim.modules.patient.test_patient import create_test_patient
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
        archetype = scenario.archetype or select_archetype(severity, patient.physiological_profile, rng)

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
    gen.add_argument("--country", default="JP", help="Country code (JP or US)")
    gen.add_argument("--period", default="2024-04-01,2025-03-31", help="Simulation period (start,end)")
    gen.add_argument("--format", nargs="+", default=["cif"], help="Output formats: cif, csv, fhir")

    # === test-disease: generate specific disease/archetype ===
    td = sub.add_parser("test-disease", help="Generate data for a specific disease and archetype")
    td.add_argument("disease_id", help="Disease ID (e.g., bacterial_pneumonia)")
    td.add_argument("-o", "--output", default="./output", help="Output directory")
    td.add_argument("-n", "--count", type=int, default=3, help="Number of patients")
    td.add_argument("--severity", default=None, help="Force severity: mild/moderate/severe")
    td.add_argument("--archetype", default=None, help="Force archetype name")
    td.add_argument("-s", "--seed", type=int, default=42, help="Random seed")
    td.add_argument("--format", nargs="+", default=["cif", "csv"], help="Output formats")

    args = parser.parse_args()

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
        config = SimulatorConfig(random_seed=args.seed)
        print(f"clinosim test-disease: {args.disease_id} x{args.count}")
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
        convert_cif_to_fhir(cif_dir, os.path.join(args.output, "fhir_r4"))

    # Summary
    n = len(dataset.patients)
    print(f"  Patients: {n}")
    if n > 0:
        print(f"  Labs: {sum(len(r.lab_results) for r in dataset.patients)}")
        print(f"  Vitals: {sum(len(r.vital_signs) for r in dataset.patients)}")
        print(f"  MARs: {sum(len(r.medication_administrations) for r in dataset.patients)}")
        print(f"  Deceased: {sum(1 for r in dataset.patients if r.deceased)}")
    print(f"  Output: {args.output}/")


if __name__ == "__main__":
    import os
    main()
