"""Outpatient visit simulation."""

from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np

from clinosim.modules.encounter.engine import create_inpatient_encounter
from clinosim.modules.observation.engine import determine_flag, generate_lab_result, get_lab_unit
from clinosim.modules.staff.engine import StaffRoster, assign_staff
from clinosim.types.clinical import ClinicalDiagnosis, ConditionEvent
from clinosim.types.encounter import (
    EncounterStatus,
    EncounterType,
    Order,
    OrderResult,
    OrderStatus,
    OrderType,
    PrescriptionRecord,
    VitalSignRecord,
)
from clinosim.types.output import CIFPatientRecord
from clinosim.types.patient import PatientProfile


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
        # Try encounter protocol YAML for chief complaint
        try:
            from clinosim.modules.encounter.protocol import load_encounter_condition
            enc_proto = load_encounter_condition(chronic_code)
            chief = enc_proto.get("chief_complaint", f"Follow-up: {chronic_code}")
        except (FileNotFoundError, Exception):
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
