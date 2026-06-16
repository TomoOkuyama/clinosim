"""CSV adapter — Stage 3: convert CIF structural data to flat CSV files."""

from __future__ import annotations

import csv
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any


def convert_cif_to_csv(cif_dir: str, output_dir: str) -> None:
    """Read CIF structural data and write flat CSV files."""
    os.makedirs(output_dir, exist_ok=True)

    structural_dir = os.path.join(cif_dir, "structural", "patients")
    if not os.path.exists(structural_dir):
        raise FileNotFoundError(f"CIF structural directory not found: {structural_dir}")

    patients_rows: list[dict] = []
    encounters_rows: list[dict] = []
    diagnoses_rows: list[dict] = []
    labs_rows: list[dict] = []
    vitals_rows: list[dict] = []
    orders_rows: list[dict] = []
    mar_rows: list[dict] = []
    proc_rows: list[dict] = []
    rehab_rows: list[dict] = []
    io_rows: list[dict] = []
    adl_rows: list[dict] = []
    rx_rows: list[dict] = []
    microbiology_rows: list[dict] = []

    for filename in sorted(os.listdir(structural_dir)):
        if not filename.endswith(".json"):
            continue
        with open(os.path.join(structural_dir, filename)) as f:
            record = json.load(f)

        patient = record.get("patient", {})
        patient_id = patient.get("patient_id", "")

        # Patients table
        name_data = patient.get("name", {})
        patients_rows.append({
            "patient_id": patient_id,
            "family_name": name_data.get("family_name", ""),
            "given_name": name_data.get("given_name", ""),
            "display_name": name_data.get("display_name", ""),
            "age": patient.get("age"),
            "sex": patient.get("sex"),
            "blood_type": patient.get("blood_type"),
            "height_cm": patient.get("height_cm"),
            "weight_kg": patient.get("weight_kg"),
            "bmi": patient.get("bmi"),
            "insurance_type": patient.get("insurance_type"),
            "smoking_status": patient.get("smoking_status"),
            "chronic_conditions": "|".join(c.get("code", "") for c in patient.get("chronic_conditions", [])),
        })

        # Encounters table
        is_readmission = record.get("is_readmission", False)
        prior_encounter_id = record.get("prior_encounter_id")
        readmission_number = record.get("readmission_number", 0)

        for enc in record.get("encounters", []):
            encounters_rows.append({
                "encounter_id": enc.get("encounter_id"),
                "patient_id": patient_id,
                "encounter_type": enc.get("encounter_type"),
                "status": enc.get("status"),
                "department_id": enc.get("department_id"),
                "admission_datetime": enc.get("admission_datetime"),
                "discharge_datetime": enc.get("discharge_datetime"),
                "chief_complaint": enc.get("chief_complaint"),
                "ward_id": enc.get("ward_id", ""),
                "bed_number": enc.get("bed_number", ""),
                "is_readmission": is_readmission,
                "prior_encounter_id": prior_encounter_id or "",
                "readmission_number": readmission_number,
            })

        # Diagnoses table
        clinical_dx = record.get("clinical_diagnosis", {})
        condition = record.get("condition_event", {})
        enc_id = record.get("encounters", [{}])[0].get("encounter_id", "")
        diagnoses_rows.append({
            "patient_id": patient_id,
            "encounter_id": enc_id,
            "admission_diagnosis_code": clinical_dx.get("admission_diagnosis_code", ""),
            "admission_diagnosis_name": clinical_dx.get("admission_diagnosis_name", ""),
            "discharge_diagnosis_code": clinical_dx.get("discharge_diagnosis_code", ""),
            "discharge_diagnosis_name": clinical_dx.get("discharge_diagnosis_name", ""),
            "diagnosis_correct": clinical_dx.get("diagnosis_correct", ""),
            "ground_truth_diseases": "|".join(condition.get("ground_truth_diseases", [])),
            "condition_type": condition.get("condition_type", ""),
            "complications": "|".join(record.get("complications_occurred", [])),
            "deceased": record.get("deceased", False),
        })

        # Lab results table
        for i, lab in enumerate(record.get("lab_results", [])):
            labs_rows.append({
                "patient_id": patient_id,
                "lab_name": lab.get("lab_name", ""),
                "result_datetime": lab.get("result_datetime"),
                "value": lab.get("value"),
                "unit": lab.get("unit"),
                "flag": lab.get("flag"),
            })

        # Vital signs table
        for vs in record.get("vital_signs", []):
            vitals_rows.append({
                "patient_id": patient_id,
                "timestamp": vs.get("timestamp"),
                "temperature": vs.get("temperature_celsius"),
                "heart_rate": vs.get("heart_rate"),
                "systolic_bp": vs.get("systolic_bp"),
                "diastolic_bp": vs.get("diastolic_bp"),
                "respiratory_rate": vs.get("respiratory_rate"),
                "spo2": vs.get("spo2"),
                "pain_score": vs.get("pain_score"),
                "nursing_note": vs.get("nursing_note", ""),
                "data_source": vs.get("data_source"),
            })

        # Orders table
        for order in record.get("orders", []):
            orders_rows.append({
                "order_id": order.get("order_id"),
                "patient_id": patient_id,
                "encounter_id": order.get("encounter_id"),
                "order_type": order.get("order_type"),
                "display_name": order.get("display_name"),
                "urgency": order.get("urgency"),
                "ordered_datetime": order.get("ordered_datetime"),
                "status": order.get("status"),
                "clinical_intent": order.get("clinical_intent"),
            })

        # Medication administration records (MAR)
        for mar in record.get("medication_administrations", []):
            mar_rows.append({
                "patient_id": patient_id,
                "order_id": mar.get("order_id"),
                "drug_name": mar.get("drug_name"),
                "scheduled_datetime": mar.get("scheduled_datetime"),
                "actual_datetime": mar.get("actual_datetime"),
                "status": mar.get("status"),
                "dose": mar.get("dose"),
                "route": mar.get("route"),
                "administered_by": mar.get("administered_by"),
                "hold_reason": mar.get("hold_reason"),
            })

        # Procedures
        from clinosim.modules.output.hospital_course_extractor import _resolve_procedure_name
        for proc in record.get("procedures", []):
            proc_rows.append({
                "patient_id": patient_id,
                "procedure_id": proc.get("procedure_id"),
                "procedure_name": _resolve_procedure_name(proc, "en"),
                "procedure_code": proc.get("procedure_code"),
                "start_datetime": proc.get("start_datetime"),
                "end_datetime": proc.get("end_datetime"),
                "duration_minutes": proc.get("duration_minutes"),
                "anesthesia_type": proc.get("anesthesia_type"),
                "asa_class": proc.get("asa_class"),
                "estimated_blood_loss_ml": proc.get("estimated_blood_loss_ml"),
                "primary_surgeon_id": proc.get("primary_surgeon_id"),
            })

        # Rehab sessions
        for rehab in record.get("rehab_sessions", []):
            rehab_rows.append({
                "patient_id": patient_id,
                "session_id": rehab.get("session_id"),
                "therapy_type": rehab.get("therapy_type"),
                "session_date": rehab.get("session_date"),
                "duration_minutes": rehab.get("duration_minutes"),
                "day_post_op": rehab.get("day_post_op"),
                "activities": "|".join(rehab.get("activities", [])),
                "patient_participation": rehab.get("patient_participation"),
                "pain_score": rehab.get("pain_score"),
                "functional_progress": rehab.get("functional_progress"),
            })

        # Intake/Output records
        for io in record.get("intake_output_records", []):
            io_rows.append({
                "patient_id": patient_id,
                "date": io.get("date"),
                "intake_iv_ml": io.get("intake_iv_ml"),
                "intake_oral_ml": io.get("intake_oral_ml"),
                "output_urine_ml": io.get("output_urine_ml"),
                "output_drain_ml": io.get("output_drain_ml"),
                "net_balance_ml": io.get("net_balance_ml"),
            })

        # ADL assessments
        for adl in record.get("adl_assessments", []):
            adl_rows.append({
                "patient_id": patient_id,
                "date": adl.get("date"),
                "barthel_score": adl.get("barthel_score"),
                "feeding": adl.get("feeding"),
                "bathing": adl.get("bathing"),
                "transfers": adl.get("transfers"),
                "mobility": adl.get("mobility"),
                "stairs": adl.get("stairs"),
            })

        # Microbiology (one row per susceptibility result; one row if no growth)
        for mb in record.get("microbiology", []):
            base = {
                "patient_id": patient_id,
                "encounter_id": mb.get("encounter_id"),
                "specimen": mb.get("specimen"),
                "specimen_snomed": mb.get("specimen_snomed"),
                "test_loinc": mb.get("test_loinc"),
                "collected_datetime": mb.get("collected_datetime"),
                "reported_datetime": mb.get("reported_datetime"),
                "growth": mb.get("growth"),
                "organism_snomed": mb.get("organism_snomed"),
                "quantitation": mb.get("quantitation"),
            }
            susceptibilities = mb.get("susceptibilities") or []
            if susceptibilities:
                for s in susceptibilities:
                    microbiology_rows.append({
                        **base,
                        "antibiotic_loinc": s.get("antibiotic_loinc"),
                        "interpretation": s.get("interpretation"),
                    })
            else:
                microbiology_rows.append({**base, "antibiotic_loinc": "", "interpretation": ""})

        # Discharge prescription
        rx = record.get("discharge_prescription")
        if rx and rx.get("items"):
            for item in rx["items"]:
                rx_rows.append({
                    "patient_id": patient_id,
                    "prescription_id": rx.get("prescription_id"),
                    "prescriber_id": rx.get("prescriber_id"),
                    "drug_name": item.get("drug_name"),
                    "dose": item.get("dose"),
                    "route": item.get("route"),
                    "duration_days": item.get("duration_days"),
                })

    # Write CSVs
    _write_csv(os.path.join(output_dir, "patients.csv"), patients_rows)
    _write_csv(os.path.join(output_dir, "encounters.csv"), encounters_rows)
    _write_csv(os.path.join(output_dir, "diagnoses.csv"), diagnoses_rows)
    _write_csv(os.path.join(output_dir, "lab_results.csv"), labs_rows)
    _write_csv(os.path.join(output_dir, "vital_signs.csv"), vitals_rows)
    _write_csv(os.path.join(output_dir, "orders.csv"), orders_rows)
    _write_csv(os.path.join(output_dir, "medication_administrations.csv"), mar_rows)
    _write_csv(os.path.join(output_dir, "procedures.csv"), proc_rows)
    _write_csv(os.path.join(output_dir, "rehab_sessions.csv"), rehab_rows)
    _write_csv(os.path.join(output_dir, "intake_output.csv"), io_rows)
    _write_csv(os.path.join(output_dir, "adl_assessments.csv"), adl_rows)
    _write_csv(os.path.join(output_dir, "prescriptions.csv"), rx_rows)
    _write_csv(os.path.join(output_dir, "microbiology.csv"), microbiology_rows)


def _write_csv(filepath: str, rows: list[dict]) -> None:
    if not rows:
        return
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
