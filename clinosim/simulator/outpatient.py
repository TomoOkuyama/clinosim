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
    country: str = "US",
) -> CIFPatientRecord:
    """Simulate a single outpatient visit (chronic follow-up or post-discharge).

    Generates: 1 encounter, 0-3 lab orders, 1 vital sign set, prescription renewal.
    """
    from clinosim.locale.text import resolve_text

    # Build visit reason from YAML spec or disease-specific post-discharge reason
    spec = followup_spec or {}
    if spec.get("visit_reason"):
        chief = resolve_text(spec["visit_reason"], country=country)
    elif post_discharge_disease:
        # Look up disease-specific post-discharge reason
        from clinosim.locale.loader import load_chronic_followup
        fu = load_chronic_followup()
        disease_fu = fu.get("_post_discharge_by_disease", {}).get(post_discharge_disease, {})
        raw = disease_fu.get("visit_reason", f"Post-discharge follow-up: {post_discharge_disease}")
        chief = resolve_text(raw, country=country)
    else:
        # Try encounter protocol YAML for chief complaint
        try:
            from clinosim.modules.encounter.protocol import load_encounter_condition
            enc_proto = load_encounter_condition(chronic_code)
            raw = enc_proto.get("chief_complaint", f"Follow-up: {chronic_code}")
            chief = resolve_text(raw, country=country)
        except (FileNotFoundError, Exception):
            chief = f"Follow-up: {chronic_code}"

    encounter = create_inpatient_encounter(
        patient.patient_id, visit_date,
        chief_complaint=chief,
        visit_number=0,  # ignored — global counter used
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

    # Vitals (subset depends on visit type and chronic condition)
    # Default profile: BP + HR (most common chronic followup measurements)
    profile_by_chronic = {
        "I10":   {"bp", "hr"},                  # HTN
        "E11.9": {"bp", "hr", "weight"},        # DM
        "E78":   {"bp", "hr"},                  # Dyslipidemia
        "I50":   {"bp", "hr", "weight", "spo2"},# HF
        "I48":   {"bp", "hr"},                  # AFib
        "I25":   {"bp", "hr"},                  # IHD
        "J44":   {"bp", "hr", "spo2", "rr"},    # COPD
        "N18":   {"bp", "hr", "weight"},        # CKD
        "E03":   {"bp", "hr"},                  # Hypothyroid
    }
    if visit_type == "post_discharge":
        # Post-discharge: full vital set
        fields = {"temp", "hr", "bp", "rr", "spo2"}
    elif chronic_code and chronic_code.split(".")[0] in profile_by_chronic:
        fields = profile_by_chronic[chronic_code.split(".")[0]]
    elif chronic_code in profile_by_chronic:
        fields = profile_by_chronic[chronic_code]
    elif visit_type == "health_screening":
        fields = {"temp", "hr", "bp", "rr", "spo2"}
    else:
        fields = {"hr", "bp"}

    baseline = patient.baseline_vitals
    raw = {
        "temperature": float(rng.normal(36.4, 0.2)),
        "heart_rate": float(baseline.heart_rate + rng.normal(0, 5)),
        "systolic_bp": float(baseline.systolic_bp + rng.normal(0, 8)),
        "diastolic_bp": float(baseline.diastolic_bp + rng.normal(0, 5)),
        "respiratory_rate": float(rng.normal(16, 1.5)),
        "spo2": float(min(99, rng.normal(97.5, 0.8))),
    }
    vitals.append(VitalSignRecord(
        timestamp=visit_date + timedelta(minutes=5),
        temperature_celsius=round(raw["temperature"], 1) if "temp" in fields else None,
        heart_rate=int(round(raw["heart_rate"])) if "hr" in fields else None,
        systolic_bp=int(round(raw["systolic_bp"])) if "bp" in fields else None,
        diastolic_bp=int(round(raw["diastolic_bp"])) if "bp" in fields else None,
        respiratory_rate=int(round(raw["respiratory_rate"])) if "rr" in fields else None,
        spo2=round(raw["spo2"], 1) if "spo2" in fields else None,
        data_source="manual",
    ))

    # Pre-assign a lab tech for outpatient labs
    lab_tech_assignment = assign_staff("lab_collection", "laboratory", roster, rng)
    lab_tech_id = lab_tech_assignment.get("performing_technician", "")

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
            ordered_by=encounter.attending_physician_id,
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
            performed_by=lab_tech_id,
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

    # Set encounter_id on all orders
    for o in orders:
        if not o.encounter_id:
            o.encounter_id = encounter.encounter_id

    # Outpatient encounter metadata
    encounter.admit_source = "outp"
    encounter.discharge_disposition = "home"
    encounter.priority = "R"
    encounter.admitting_physician_id = encounter.attending_physician_id
    encounter.discharging_physician_id = encounter.attending_physician_id

    # Determine diagnosis code — prefer encounter YAML, fall back to chronic/Z-code
    dx_code = ""
    dx_name = ""

    # First priority: encounter YAML icd10_code (for screenings, vaccinations, etc.)
    if chronic_code:
        try:
            from clinosim.modules.encounter.protocol import load_encounter_condition
            enc_proto = load_encounter_condition(chronic_code)
            dx_code = enc_proto.get("icd10_code", "")
            dx_name = enc_proto.get("icd10_display", "")
        except (FileNotFoundError, Exception):
            pass

    # Second priority: chronic condition ICD code directly
    if not dx_code and chronic_code:
        # Check if it looks like an ICD code (letter + digit)
        if len(chronic_code) >= 2 and chronic_code[0].isalpha() and chronic_code[1].isdigit():
            dx_code = chronic_code
            from clinosim.modules.patient.activator import CONDITION_NAMES
            dx_name = CONDITION_NAMES.get(chronic_code, chronic_code)

    # Third priority: post-discharge follow-up
    if not dx_code and post_discharge_disease:
        dx_code = "Z09"
        dx_name = f"Follow-up examination after treatment for {post_discharge_disease.replace('_', ' ')}"

    # Final fallback
    if not dx_code:
        dx_code = "Z09"
        dx_name = "Encounter for follow-up examination"

    condition_event = ConditionEvent(
        condition_id=f"COND-{patient.patient_id}-OPD",
        condition_type="chronic_followup" if chronic_code else "post_discharge_followup",
        ground_truth_diseases=[dx_code] if dx_code else [],
    )
    clinical_diagnosis = ClinicalDiagnosis(
        admission_diagnosis_code=dx_code,
        admission_diagnosis_system="icd-10" if country == "JP" else "icd-10-cm",
        discharge_diagnosis_code=dx_code,
        discharge_diagnosis_system="icd-10" if country == "JP" else "icd-10-cm",
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
