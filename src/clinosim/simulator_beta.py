"""Simulator — v0.1-beta: population-driven, multiple patients, all archetypes.

Generates a catchment population, runs life events, activates patients,
simulates hospital encounters with varying archetypes, and writes CIF.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta

import numpy as np

from clinosim.modules.clinical_course.engine import get_daily_directive, select_archetype
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
from clinosim.types.clinical import PhysiologicalState, StateChangeDirective
from clinosim.types.config import SimulatorConfig
from clinosim.types.encounter import (
    EncounterStatus,
    Order,
    OrderResult,
    OrderStatus,
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
        protocol = protocols.get(disease_id)
        if protocol is None:
            continue  # unknown disease, skip

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

        for day in range(target_los):
            directive = get_daily_directive(archetype, day, patient.physiological_profile)
            state = update(state, directive, timedelta(days=1))
            state_history.append(deepcopy(state))

            # Daily labs
            if day >= 1:
                lab_time = datetime(
                    admission_time.year, admission_time.month, admission_time.day, 6, 0
                ) + timedelta(days=day)
                daily_orders = place_daily_lab_orders(
                    protocol.model_dump(), patient.patient_id, encounter.encounter_id,
                    day, lab_time, healthcare.lab_frequency_multiplier, rng,
                )
                all_orders.extend(daily_orders)

            # Lab results
            true_labs = derive_lab_values(state, sex=patient.sex, age=patient.age, has_diabetes=has_diabetes)
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

            # Vitals
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

        encounter.status = EncounterStatus.COMPLETED
        encounter.discharge_datetime = admission_time + timedelta(days=target_los, hours=14)

        patient_records.append(CIFPatientRecord(
            patient=patient,
            encounters=[encounter],
            orders=all_orders,
            vital_signs=all_vitals,
            lab_results=all_lab_results,
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
