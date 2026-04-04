"""Simulator — v0.1-beta: population-driven, multiple patients, all archetypes.

Generates a catchment population, runs life events, activates patients,
simulates hospital encounters with varying archetypes, and writes CIF.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta

import numpy as np

from clinosim.modules.clinical_course.engine import (
    evaluate_complications,
    get_daily_directive,
    select_archetype,
)
from clinosim.modules.disease.protocol import load_disease_protocol
from clinosim.modules.encounter.engine import create_inpatient_encounter
from clinosim.modules.healthcare_system.loader import load_healthcare_config
from clinosim.modules.observation.engine import determine_flag, generate_lab_result
from clinosim.modules.order.engine import (
    calculate_lab_result_time,
    place_admission_orders,
    place_daily_lab_orders,
)
from clinosim.modules.output.cif_writer import write_cif
from clinosim.modules.diagnosis.engine import (
    initialize_differential,
    update_differential,
    get_current_diagnosis_code,
)
from clinosim.modules.patient.activator import activate_patient
from clinosim.modules.physiology.engine import (
    apply_disease_onset,
    derive_lab_values,
    derive_vital_signs,
    initialize_state,
    update,
)
from clinosim.modules.population.engine import (
    generate_monthly_events,
    generate_population,
)
from clinosim.modules.staff.engine import assign_staff, generate_roster
from clinosim.types.clinical import (
    ClinicalDiagnosis,
    ConditionEvent,
    PhysiologicalState,
    StateChangeDirective,
)
from clinosim.types.config import ForcedScenario, SimulatorConfig
from clinosim.types.encounter import (
    EncounterStatus,
    Order,
    OrderResult,
    OrderStatus,
    OrderType,
    VitalSignRecord,
)
from clinosim.types.output import CIFDataset, CIFMetadata, CIFPatientRecord


def run_beta(config: SimulatorConfig | None = None) -> CIFDataset:
    """Run v0.1-beta: population-driven, multiple patients."""
    if config is None:
        config = SimulatorConfig()

    rng = np.random.default_rng(config.random_seed)

    # --- Load modules ---
    healthcare = load_healthcare_config(config.country)
    # Load all Phase 1 disease protocols
    protocols = {
        "bacterial_pneumonia": load_disease_protocol("bacterial_pneumonia"),
        "heart_failure_exacerbation": load_disease_protocol("heart_failure_exacerbation"),
        "hip_fracture": load_disease_protocol("hip_fracture"),
    }
    roster = generate_roster(config.hospital_scale, config.country, rng)

    # --- Generate population ---
    population = generate_population(config.catchment_population, config.country, rng)
    print(f"  Population: {population.total_persons} persons")

    # --- Run life events ---
    start_year, start_month = int(config.time_range[0][:4]), int(config.time_range[0][5:7])
    end_year, end_month = int(config.time_range[1][:4]), int(config.time_range[1][5:7])

    all_events = []
    year, month = start_year, start_month
    while (year, month) <= (end_year, end_month):
        events = generate_monthly_events(population, year, month, rng)
        all_events.extend(events)
        month += 1
        if month > 12:
            month = 1
            year += 1

    hospital_events = [e for e in all_events if e.requires_hospital]
    print(f"  Life events: {len(all_events)} total, {len(hospital_events)} requiring hospital")

    # --- Process forced scenarios first ---
    forced_events = []
    for scenario in config.forced_scenarios:
        for i in range(scenario.count):
            forced_events.append(scenario)

    # --- Simulate each hospital visit ---
    patient_records: list[CIFPatientRecord] = []

    for event in hospital_events:
        person = population.get_person(event.person_id)
        if person is None:
            continue

        # Layer 1 → Layer 2
        patient = activate_patient(person, rng, config.country)

        # Select protocol for this disease
        disease_id = event.disease_id

        # Unknown condition: generate minimal encounter without disease protocol
        if event.condition_type == "unknown" or disease_id.startswith("unknown_"):
            record = _simulate_unknown_condition(patient, event, rng, healthcare)
            if record:
                patient_records.append(record)
                person.has_visited_hospital = True
                person.visit_count += 1
            continue

        protocol = protocols.get(disease_id)
        if protocol is None:
            continue

        # Mixed condition: note ground truth includes multiple diseases
        condition_event = ConditionEvent(
            condition_id=f"COND-{patient.patient_id}-001",
            condition_type=event.condition_type,
            ground_truth_diseases=[disease_id] if event.condition_type == "known_disease"
                else [disease_id, "heart_failure_exacerbation"],  # mixed: pneumonia + HF
        )

        # Select archetype
        severity = "moderate" if event.severity > 0.3 else "mild"
        if event.severity > 0.7:
            severity = "severe"
        # Hip fracture: never mild
        if disease_id == "hip_fracture" and severity == "mild":
            severity = "moderate"
        archetype = select_archetype(severity, patient.physiological_profile, rng)

        # Initialize state
        state = initialize_state(
            patient.physiological_profile,
            patient.chronic_conditions,
            patient_id=patient.patient_id,
        )
        state = apply_disease_onset(state, severity, protocol.initial_state_impact)

        # Create encounter
        admission_time = datetime(
            event.timestamp.year, event.timestamp.month, event.timestamp.day,
            int(rng.integers(8, 22)), 0,
        )
        encounter = create_inpatient_encounter(
            patient_id=patient.patient_id,
            admission_datetime=admission_time,
        )

        # LOS
        los_config = protocol.target_los.get("japan", {}).get(severity, {"mean": 14, "sd": 4, "min": 5, "max": 30})
        target_los = int(rng.normal(los_config["mean"], los_config["sd"]))
        target_los = max(los_config.get("min", 5), min(los_config.get("max", 30), target_los))

        # Simulate
        all_orders: list[Order] = []
        all_lab_results: list[OrderResult] = []
        all_vitals: list[VitalSignRecord] = []
        state_history: list[PhysiologicalState] = [deepcopy(state)]

        # Admission orders
        admission_orders = place_admission_orders(
            protocol.model_dump(), patient.patient_id, encounter.encounter_id,
            admission_time, country="japan", rng=rng,
        )
        all_orders.extend(admission_orders)

        has_diabetes = any(c.code.startswith("E11") for c in patient.chronic_conditions)

        # Initialize differential diagnosis
        differential = initialize_differential(disease_id, patient.age)

        # Track treatment state
        treatment_changed = False
        treatment_change_day: int | None = None

        # Track complications
        active_complications: set[str] = set()
        complications_occurred: list[str] = []

        for day in range(target_los):
            # --- Clinical course: state progression ---
            directive = get_daily_directive(archetype, day, patient.physiological_profile)
            state = update(state, directive, timedelta(days=1))
            state_history.append(deepcopy(state))

            # --- Daily labs ---
            if day >= 1:
                lab_time = datetime(
                    admission_time.year, admission_time.month, admission_time.day, 6, 0
                ) + timedelta(days=day)
                daily_orders = place_daily_lab_orders(
                    protocol.model_dump(), patient.patient_id, encounter.encounter_id,
                    day, lab_time, healthcare.lab_frequency_multiplier, rng,
                )
                all_orders.extend(daily_orders)

            # --- Generate lab results ---
            true_labs = derive_lab_values(state, sex=patient.sex, age=patient.age, has_diabetes=has_diabetes)
            todays_results: list[tuple[str, float]] = []
            for order in all_orders:
                if (order.order_type.value == "lab"
                    and order.status == OrderStatus.PLACED
                    and order.display_name in true_labs):
                    result_time = calculate_lab_result_time(order, rng)
                    observed = generate_lab_result(order.display_name, true_labs[order.display_name], rng)
                    flag = determine_flag(order.display_name, observed, sex=patient.sex)
                    order.result = OrderResult(
                        result_datetime=result_time, performed_by="TECH-001",
                        value=observed, unit="", flag=flag,
                    )
                    order.status = OrderStatus.RESULTED
                    all_lab_results.append(order.result)
                    todays_results.append((order.display_name, observed))

            # --- Diagnosis update (Bayesian, during morning rounds) ---
            if day >= 1 and todays_results:
                findings: list[tuple[str, bool]] = []
                for lab_name, value in todays_results:
                    if lab_name == "CRP" and value > 100:
                        findings.append(("crp_above_100", True))
                    elif lab_name == "CRP" and value <= 100:
                        findings.append(("crp_above_100", False))
                    if lab_name == "WBC" and value > 15000:
                        findings.append(("wbc_elevated", True))
                    elif lab_name == "WBC" and value <= 15000:
                        findings.append(("wbc_elevated", False))

                # Day 0-1: imaging findings (simulated)
                if day == 1 and disease_id == "bacterial_pneumonia":
                    findings.append(("chest_xray_consolidation", True))
                    findings.append(("procalcitonin_elevated", True))

                if findings:
                    differential = update_differential(differential, findings)

            # --- Treatment evaluation (Day 3: check response) ---
            if day == 3 and not treatment_changed:
                # Check if treatment is working
                if state.inflammation_level > 0.5 and archetype in ("treatment_resistant", "gradual_deterioration"):
                    # Treatment not working → escalate
                    treatment_changed = True
                    treatment_change_day = day
                    # Place escalation antibiotic order
                    escalation = protocol.drugs.get("escalation", {}).get("japan", [])
                    if escalation:
                        esc_drug = escalation[0] if isinstance(escalation, list) else escalation
                        esc_order = Order(
                            order_id=f"ORD-{patient.patient_id}-ESC-001",
                            encounter_id=encounter.encounter_id,
                            patient_id=patient.patient_id,
                            order_type=OrderType.MEDICATION,
                            display_name=f"Escalation: {esc_drug.get('drug', 'Meropenem')}",
                            urgency="urgent",
                            clinical_intent=f"Day {day}: no improvement, antibiotic escalation",
                            ordered_datetime=admission_time + timedelta(days=day, hours=10),
                            ordered_by="STAFF-PLACEHOLDER-001",
                            status=OrderStatus.PLACED,
                        )
                        all_orders.append(esc_order)

            # --- Vitals ---
            for hour in [6, 14, 18]:
                vit_time = datetime(
                    admission_time.year, admission_time.month, admission_time.day, hour, 0
                ) + timedelta(days=day)
                if vit_time < admission_time:
                    continue
                vitals_dict = derive_vital_signs(state, patient.baseline_vitals, vit_time)
                for key in vitals_dict:
                    vitals_dict[key] += float(rng.normal(0, 0.5 if key == "temperature" else 2))
                    if key == "spo2":
                        vitals_dict[key] = min(100.0, max(60.0, vitals_dict[key]))
                record = VitalSignRecord(
                    temperature_celsius=round(vitals_dict["temperature"], 1),
                    heart_rate=int(round(vitals_dict["heart_rate"])),
                    systolic_bp=int(round(vitals_dict["systolic_bp"])),
                    diastolic_bp=int(round(vitals_dict["diastolic_bp"])),
                    respiratory_rate=int(round(vitals_dict["respiratory_rate"])),
                    spo2=round(vitals_dict["spo2"], 1),
                    data_source="manual",
                )
                all_vitals.append(record)

            # --- Complication evaluation ---
            complication_list = protocol.complications if protocol.complications else []
            if complication_list and day >= 1:
                triggered = evaluate_complications(
                    day, state, patient, complication_list, active_complications, rng
                )
                for comp in triggered:
                    # Apply complication state impact
                    impact = comp.get("state_impact", {})
                    for var, delta in impact.items():
                        current = getattr(state, var, None)
                        if current is not None:
                            setattr(state, var, max(-1.0, min(1.0, current + delta)))
                    complications_occurred.append(comp.get("name", "unknown"))

        # Final diagnosis code
        dx_code, dx_name = get_current_diagnosis_code(differential)

        # Build clinical diagnosis (AD-28)
        clinical_diagnosis = ClinicalDiagnosis(
            admission_diagnosis_code="J18.9" if disease_id == "bacterial_pneumonia" else protocol.icd_codes.get("primary", ""),
            admission_diagnosis_name=disease_id.replace("_", " ").title(),
            discharge_diagnosis_code=dx_code,
            discharge_diagnosis_name=dx_name,
            diagnosis_correct=(dx_code != "R05"),  # simplified: correct if not "unspecified"
        )

        encounter.status = EncounterStatus.COMPLETED
        encounter.discharge_datetime = admission_time + timedelta(days=target_los, hours=14)

        patient_records.append(CIFPatientRecord(
            patient=patient,
            encounters=[encounter],
            orders=all_orders,
            vital_signs=all_vitals,
            lab_results=all_lab_results,
            condition_event=condition_event,
            clinical_diagnosis=clinical_diagnosis,
            complications_occurred=complications_occurred,
            physiological_states=state_history,
        ))

        # Mark as visited
        person.has_visited_hospital = True
        person.visit_count += 1

    metadata = CIFMetadata(
        clinosim_version="0.1.0-beta",
        random_seed=config.random_seed,
        country=config.country,
        hospital_scale=config.hospital_scale,
        total_patients_generated=len(patient_records),
        llm_mode=config.llm.judgment.mode,
    )

    return CIFDataset(metadata=metadata, patients=patient_records)


def _simulate_unknown_condition(
    patient: Any,
    event: Any,
    rng: np.random.Generator,
    healthcare: Any,
) -> CIFPatientRecord | None:
    """Simulate a patient with unknown/idiopathic condition.

    Generates a short admission with nonspecific findings, workup,
    and discharge with unresolved diagnosis.
    """
    from clinosim.modules.physiology.engine import initialize_state, derive_lab_values, derive_vital_signs

    state = initialize_state(
        patient.physiological_profile, patient.chronic_conditions,
        patient_id=patient.patient_id,
    )

    # Apply nonspecific state change (mild inflammation, no clear pattern)
    state.inflammation_level += float(rng.uniform(0.10, 0.30))

    admission_time = datetime(
        event.timestamp.year, event.timestamp.month, event.timestamp.day,
        int(rng.integers(8, 22)), 0,
    )
    encounter = create_inpatient_encounter(
        patient_id=patient.patient_id,
        admission_datetime=admission_time,
        chief_complaint=event.disease_id.replace("unknown_", "").replace("_", " "),
    )

    # Short stay: 5-10 days (workup then discharge unresolved)
    target_los = int(rng.integers(5, 11))

    all_vitals: list[VitalSignRecord] = []
    state_history = [deepcopy(state)]

    for day in range(target_los):
        # Slow random walk (no clear trajectory)
        state.inflammation_level += float(rng.normal(0, 0.02))
        state.inflammation_level = max(0.0, min(1.0, state.inflammation_level))
        state_history.append(deepcopy(state))

        for hour in [6, 14, 18]:
            vit_time = admission_time + timedelta(days=day, hours=hour - admission_time.hour)
            if vit_time < admission_time:
                continue
            vitals_dict = derive_vital_signs(state, patient.baseline_vitals, vit_time)
            for key in vitals_dict:
                vitals_dict[key] += float(rng.normal(0, 0.5 if key == "temperature" else 2))
            all_vitals.append(VitalSignRecord(
                temperature_celsius=round(vitals_dict["temperature"], 1),
                heart_rate=int(round(vitals_dict["heart_rate"])),
                systolic_bp=int(round(vitals_dict["systolic_bp"])),
                diastolic_bp=int(round(vitals_dict["diastolic_bp"])),
                respiratory_rate=int(round(vitals_dict["respiratory_rate"])),
                spo2=round(min(100.0, max(60.0, vitals_dict["spo2"])), 1),
                data_source="manual",
            ))

    encounter.status = EncounterStatus.COMPLETED
    encounter.discharge_datetime = admission_time + timedelta(days=target_los, hours=14)

    condition_event = ConditionEvent(
        condition_id=f"COND-{patient.patient_id}-UNK",
        condition_type="unknown",
        symptom_pattern=event.disease_id,
    )

    clinical_diagnosis = ClinicalDiagnosis(
        admission_diagnosis_code="R50.9" if "fever" in event.disease_id else "R53.1",
        admission_diagnosis_name=event.disease_id.replace("unknown_", "").replace("_", " ").title(),
        discharge_diagnosis_code="R50.9" if "fever" in event.disease_id else "R53.1",
        discharge_diagnosis_name="Unresolved " + event.disease_id.replace("unknown_", "").replace("_", " "),
        diagnosis_correct=False,  # by definition: unknown cause
    )

    return CIFPatientRecord(
        patient=patient,
        encounters=[encounter],
        vital_signs=all_vitals,
        condition_event=condition_event,
        clinical_diagnosis=clinical_diagnosis,
        physiological_states=state_history,
    )


def main() -> None:
    import sys
    output_dir = sys.argv[1] if len(sys.argv) > 1 else "./output/cif_beta"
    pop_size = int(sys.argv[2]) if len(sys.argv) > 2 else 10_000

    print(f"clinosim v0.1-beta: population={pop_size}")
    config = SimulatorConfig(
        catchment_population=pop_size,
        time_range=("2024-04-01", "2025-03-31"),
        random_seed=42,
    )
    dataset = run_beta(config)

    write_cif(dataset, output_dir)

    print(f"  Patients generated: {len(dataset.patients)}")
    if dataset.patients:
        archetypes: dict[str, int] = {}
        total_labs = 0
        total_vitals = 0
        for r in dataset.patients:
            total_labs += len(r.lab_results)
            total_vitals += len(r.vital_signs)
        print(f"  Total lab results: {total_labs}")
        print(f"  Total vital signs: {total_vitals}")
        ages = [r.patient.age for r in dataset.patients]
        print(f"  Age range: {min(ages)}-{max(ages)} (mean {sum(ages)/len(ages):.0f})")
    print(f"  Output: {output_dir}/")


if __name__ == "__main__":
    main()
