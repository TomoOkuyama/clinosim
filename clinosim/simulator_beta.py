"""Simulator — population-driven, multiple patients, all archetypes.

Refactored into clear functions:
  run_beta()           — orchestrator
  _simulate_patient()  — one patient's full hospital encounter
  _run_daily_loop()    — daily cycle (state update, labs, vitals, complications)
  _generate_mar()      — medication administration records
  _build_discharge_rx() — discharge prescription
"""

from __future__ import annotations

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

        record = _simulate_patient(
            patient, event, disease_id, protocol, healthcare, roster, config, rng,
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
) -> CIFPatientRecord:
    """Simulate one patient's complete hospital encounter."""

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

    # Create encounter
    admission_time = datetime(event.timestamp.year, event.timestamp.month, event.timestamp.day,
                               int(rng.integers(8, 22)), 0)
    encounter = create_inpatient_encounter(patient.patient_id, admission_time)

    # Staff assignment
    staff = assign_staff("admission", "internal_medicine", roster, rng)
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

    clinical_diagnosis = ClinicalDiagnosis(
        admission_diagnosis_code=protocol.icd_codes.get("primary", ""),
        admission_diagnosis_name=disease_id.replace("_", " ").title(),
        discharge_diagnosis_code=dx_code,
        discharge_diagnosis_name=dx_name,
        diagnosis_correct=(dx_code != "R05"),
    )

    condition_event = ConditionEvent(
        condition_id=f"COND-{patient.patient_id}-001",
        condition_type=event.condition_type,
        ground_truth_diseases=[disease_id] if event.condition_type == "known_disease"
            else [disease_id, "heart_failure_exacerbation"],
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

        # Lab results
        true_labs = derive_lab_values(state, sex=patient.sex, age=patient.age, has_diabetes=has_diabetes)
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
        # Determine administration times based on route/frequency
        if "IV" in drug_name.upper() or "iv" in order.clinical_intent.lower():
            # IV: typically q6h or q8h
            admin_hours = [6, 12, 18, 0] if "q6h" in drug_name.lower() else [8, 16, 0]
        elif "daily" in drug_name.lower() or "SC" in drug_name.upper():
            admin_hours = [8]  # once daily
        else:
            admin_hours = [8, 14, 20]  # TID default

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
    """Simulate patient with unknown/idiopathic condition."""
    state = initialize_state(patient.physiological_profile, patient.chronic_conditions, patient.patient_id)
    state.inflammation_level += float(rng.uniform(0.10, 0.30))

    admission_time = datetime(event.timestamp.year, event.timestamp.month, event.timestamp.day,
                               int(rng.integers(8, 22)), 0)
    encounter = create_inpatient_encounter(patient.patient_id, admission_time,
                                            chief_complaint=event.disease_id.replace("unknown_", "").replace("_", " "))
    encounter.attending_physician_id = assign_staff("admission", "internal_medicine", roster, rng).get("attending_physician", "DR-001")

    target_los = int(rng.integers(5, 11))
    all_vitals: list[VitalSignRecord] = []
    state_history = [deepcopy(state)]

    for day in range(target_los):
        state.inflammation_level += float(rng.normal(0, 0.02))
        state.inflammation_level = max(0.0, min(1.0, state.inflammation_level))
        state_history.append(deepcopy(state))

        for v in _generate_vitals(state, patient, day, admission_time, rng):
            all_vitals.append(v)

    encounter.status = EncounterStatus.COMPLETED
    encounter.discharge_datetime = admission_time + timedelta(days=target_los, hours=14)

    return CIFPatientRecord(
        patient=patient, encounters=[encounter], vital_signs=all_vitals,
        condition_event=ConditionEvent(condition_id=f"COND-{patient.patient_id}-UNK",
                                       condition_type="unknown", symptom_pattern=event.disease_id),
        clinical_diagnosis=ClinicalDiagnosis(
            admission_diagnosis_code="R50.9" if "fever" in event.disease_id else "R53.1",
            admission_diagnosis_name=event.disease_id.replace("unknown_", "").replace("_", " ").title(),
            discharge_diagnosis_code="R50.9" if "fever" in event.disease_id else "R53.1",
            discharge_diagnosis_name="Unresolved " + event.disease_id.replace("unknown_", "").replace("_", " "),
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


def main() -> None:
    import sys
    output_dir = sys.argv[1] if len(sys.argv) > 1 else "./output/cif_beta"
    pop_size = int(sys.argv[2]) if len(sys.argv) > 2 else 10_000

    print(f"clinosim v0.1: population={pop_size}")
    config = SimulatorConfig(
        catchment_population=pop_size,
        time_range=("2024-04-01", "2025-03-31"),
        random_seed=42,
    )
    dataset = run_beta(config)
    write_cif(dataset, output_dir)

    print(f"  Patients: {len(dataset.patients)}")
    if dataset.patients:
        total_labs = sum(len(r.lab_results) for r in dataset.patients)
        total_vitals = sum(len(r.vital_signs) for r in dataset.patients)
        total_mars = sum(len(r.medication_administrations) for r in dataset.patients)
        total_deceased = sum(1 for r in dataset.patients if r.deceased)
        print(f"  Labs: {total_labs}, Vitals: {total_vitals}, MARs: {total_mars}")
        print(f"  Deceased: {total_deceased}")
    print(f"  Output: {output_dir}/")


if __name__ == "__main__":
    main()
