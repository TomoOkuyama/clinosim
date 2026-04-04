"""Simulator — v0.1-alpha: single patient, single disease, linear inpatient.

Wires all modules together for end-to-end data generation.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta

import numpy as np

from clinosim.modules.disease.protocol import load_disease_protocol
from clinosim.modules.encounter.engine import (
    create_inpatient_encounter,
    generate_encounter_timeline,
)
from clinosim.modules.healthcare_system.loader import load_healthcare_config
from clinosim.modules.observation.engine import (
    determine_flag,
    generate_lab_result,
)
from clinosim.modules.order.engine import (
    calculate_lab_result_time,
    place_admission_orders,
    place_daily_lab_orders,
)
from clinosim.modules.output.cif_writer import write_cif
from clinosim.modules.patient.test_patient import create_test_patient
from clinosim.modules.physiology.engine import (
    apply_disease_onset,
    derive_lab_values,
    derive_vital_signs,
    initialize_state,
    update,
)
from clinosim.types.clinical import PhysiologicalState, StateChangeDirective
from clinosim.types.config import SimulatorConfig
from clinosim.types.encounter import (
    Encounter,
    EncounterStatus,
    Order,
    OrderResult,
    OrderStatus,
    VitalSignRecord,
)
from clinosim.types.output import CIFDataset, CIFMetadata, CIFPatientRecord
from clinosim.types.patient import PatientProfile


def run_alpha(config: SimulatorConfig | None = None) -> CIFDataset:
    """Run v0.1-alpha simulation: 1 pneumonia patient, 14-day inpatient stay."""

    if config is None:
        config = SimulatorConfig()

    rng = np.random.default_rng(config.random_seed)

    # --- Load modules ---
    healthcare = load_healthcare_config(config.country)
    protocol = load_disease_protocol("bacterial_pneumonia")
    patient = create_test_patient()

    # --- Initialize physiological state ---
    state = initialize_state(
        patient.physiological_profile,
        patient.chronic_conditions,
        patient_id=patient.patient_id,
    )

    # Apply disease onset (moderate pneumonia)
    state = apply_disease_onset(state, "moderate", protocol.initial_state_impact)

    # --- Create encounter ---
    admission_time = datetime(2024, 6, 15, 18, 0)  # Saturday 6 PM (ED → admission)
    encounter = create_inpatient_encounter(
        patient_id=patient.patient_id,
        admission_datetime=admission_time,
    )

    # --- Determine LOS (smooth_recovery archetype for alpha) ---
    los_config = protocol.target_los.get("japan", {}).get("moderate", {})
    target_los = int(rng.normal(los_config.get("mean", 14), los_config.get("sd", 4)))
    target_los = max(los_config.get("min", 7), min(los_config.get("max", 28), target_los))

    # --- Generate encounter timeline ---
    timeline = generate_encounter_timeline(encounter, target_los)

    # --- Define smooth_recovery trajectory ---
    # inflammation: rises Day 0-1, then steadily declines
    def get_daily_directive(day: int) -> StateChangeDirective:
        """Smooth recovery trajectory for bacterial pneumonia."""
        if day == 0:
            delta_infl = 0.05  # slight rise (lag effect)
        elif day == 1:
            delta_infl = -0.02  # turning point
        elif day <= 3:
            delta_infl = -0.08
        elif day <= 7:
            delta_infl = -0.06
        elif day <= 10:
            delta_infl = -0.04
        else:
            delta_infl = -0.02

        # Volume recovery (rehydration)
        delta_vol = 0.03 if day <= 5 else 0.01

        return StateChangeDirective(
            source="disease_progression",
            changes={
                "inflammation_level": delta_infl,
                "volume_status": delta_vol,
                "renal_function": 0.01 if day >= 2 else 0.0,  # gradual recovery
            },
            reason=f"smooth_recovery_day{day}",
        )

    # --- Simulate day by day ---
    all_orders: list[Order] = []
    all_lab_results: list[OrderResult] = []
    all_vitals: list[VitalSignRecord] = []
    state_history: list[PhysiologicalState] = [deepcopy(state)]

    # Place admission orders
    admission_orders = place_admission_orders(
        protocol.model_dump(),
        patient.patient_id,
        encounter.encounter_id,
        admission_time,
        country="japan",
        rng=rng,
    )
    all_orders.extend(admission_orders)

    has_diabetes = any(c.code.startswith("E11") for c in patient.chronic_conditions)

    for day in range(target_los):
        # --- State update ---
        directive = get_daily_directive(day)
        state = update(state, directive, timedelta(days=1))
        state_history.append(deepcopy(state))

        # --- Daily lab orders (from Day 1 onward) ---
        if day >= 1:
            lab_order_time = datetime(
                admission_time.year, admission_time.month, admission_time.day, 6, 0
            ) + timedelta(days=day)
            daily_orders = place_daily_lab_orders(
                protocol.model_dump(),
                patient.patient_id,
                encounter.encounter_id,
                day,
                lab_order_time,
                healthcare.lab_frequency_multiplier,
                rng,
            )
            all_orders.extend(daily_orders)

        # --- Generate lab results for today's orders ---
        todays_lab_orders = [
            o for o in all_orders
            if o.order_type.value == "lab"
            and o.status == OrderStatus.PLACED
            and o.ordered_datetime.date() <= (admission_time + timedelta(days=day)).date()
        ]

        true_labs = derive_lab_values(
            state,
            sex=patient.sex,
            age=patient.age,
            has_diabetes=has_diabetes,
        )

        for order in todays_lab_orders:
            lab_name = order.display_name
            if lab_name in true_labs:
                result_time = calculate_lab_result_time(order, rng)
                observed_value = generate_lab_result(lab_name, true_labs[lab_name], rng)
                flag = determine_flag(lab_name, observed_value, sex=patient.sex)

                order.result = OrderResult(
                    result_datetime=result_time,
                    performed_by="TECH-PLACEHOLDER-001",
                    value=observed_value,
                    unit="",
                    flag=flag,
                )
                order.status = OrderStatus.RESULTED
                all_lab_results.append(order.result)

        # --- Generate vitals (morning, afternoon, evening) ---
        for hour in [6, 14, 18]:
            vit_time = datetime(
                admission_time.year, admission_time.month, admission_time.day, hour, 0
            ) + timedelta(days=day)

            if vit_time < admission_time:
                continue

            vitals_dict = derive_vital_signs(state, patient.baseline_vitals, vit_time)
            # Add jitter
            for key in ["temperature", "heart_rate", "systolic_bp", "diastolic_bp", "respiratory_rate", "spo2"]:
                if key in vitals_dict:
                    jitter = float(rng.normal(0, 0.5 if key == "temperature" else 2))
                    vitals_dict[key] = vitals_dict[key] + jitter
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

    # --- Complete encounter ---
    encounter.status = EncounterStatus.COMPLETED
    encounter.discharge_datetime = admission_time + timedelta(days=target_los, hours=14)

    # --- Build CIF ---
    patient_record = CIFPatientRecord(
        patient=patient,
        encounters=[encounter],
        orders=all_orders,
        vital_signs=all_vitals,
        lab_results=all_lab_results,
        physiological_states=state_history,
    )

    metadata = CIFMetadata(
        clinosim_version="0.1.0-alpha",
        random_seed=config.random_seed,
        country=config.country,
        hospital_scale=config.hospital_scale,
        total_patients_generated=1,
        llm_mode="none",
    )

    return CIFDataset(metadata=metadata, patients=[patient_record])


def main() -> None:
    """CLI entry point for v0.1-alpha."""
    import sys

    output_dir = sys.argv[1] if len(sys.argv) > 1 else "./output/cif"

    print("clinosim v0.1-alpha: generating 1 pneumonia patient...")
    dataset = run_alpha()

    write_cif(dataset, output_dir)

    # Summary
    record = dataset.patients[0]
    print(f"  Patient: {record.patient.patient_id} ({record.patient.age}yo {record.patient.sex})")
    print(f"  Encounter: {record.encounters[0].encounter_type.value}")
    print(f"  LOS: {(record.encounters[0].discharge_datetime - record.encounters[0].admission_datetime).days} days")  # type: ignore
    print(f"  Lab results: {len(record.lab_results)}")
    print(f"  Vital signs: {len(record.vital_signs)}")
    print(f"  Orders: {len(record.orders)}")
    print(f"  State snapshots: {len(record.physiological_states)}")
    print(f"  Output: {output_dir}/")


if __name__ == "__main__":
    main()
