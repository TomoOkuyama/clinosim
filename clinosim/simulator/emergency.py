"""Emergency department visit simulation."""

from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np

from clinosim.modules.encounter.engine import create_inpatient_encounter
from clinosim.modules.observation.engine import get_lab_unit
from clinosim.modules.staff.engine import StaffRoster, assign_staff
from clinosim.types.clinical import ClinicalDiagnosis, ConditionEvent
from clinosim.types.encounter import (
    EncounterStatus,
    EncounterType,
    Order,
    OrderResult,
    OrderStatus,
    OrderType,
    VitalSignRecord,
)
from clinosim.types.output import CIFPatientRecord
from clinosim.types.patient import PatientProfile


def _simulate_ed_visit(
    patient: PatientProfile,
    condition: dict,
    visit_time: datetime,
    roster: StaffRoster,
    rng: np.random.Generator,
    country: str = "US",
) -> CIFPatientRecord:
    """Simulate an ED visit using YAML protocol if available, else basic."""
    from clinosim.modules.observation.engine import generate_lab_result, determine_flag

    # Try to load detailed YAML protocol
    cond_name = condition.get("name", condition.get("condition_id", "ed_visit"))
    try:
        from clinosim.modules.encounter.protocol import load_encounter_condition
        protocol = load_encounter_condition(cond_name)
    except (FileNotFoundError, Exception):
        protocol = None

    from clinosim.locale.text import resolve_text
    raw_chief = (protocol or condition).get("chief_complaint", cond_name)
    chief = resolve_text(raw_chief, country=country)

    encounter = create_inpatient_encounter(
        patient.patient_id, visit_time,
        chief_complaint=chief,
    )
    proto_enc_type = (protocol or condition).get("encounter_type", "emergency")
    encounter.encounter_type = EncounterType.OUTPATIENT if proto_enc_type == "outpatient" else EncounterType.EMERGENCY
    encounter.status = EncounterStatus.COMPLETED

    staff = assign_staff("admission", "internal_medicine", roster, rng)
    encounter.attending_physician_id = staff.get("attending_physician", "DR-001")

    # ED stay duration from protocol or default
    if protocol:
        sev_dist = protocol.get("severity_distribution", {})
        sev_probs = [float(sev_dist.get(s, 0.0)) for s in ["mild", "moderate", "severe"]]
        total_p = sum(sev_probs)
        if total_p <= 0:
            sev_probs = [0.33, 0.34, 0.33]
        else:
            sev_probs = [p / total_p for p in sev_probs]
        severity = str(rng.choice(["mild", "moderate", "severe"], p=sev_probs))
        stay_cfg = protocol.get("ed_stay_hours", {}).get(severity, {"mean": 3, "sd": 1})
        ed_hours = float(rng.normal(stay_cfg["mean"], stay_cfg["sd"]))
    else:
        ed_hours = float(rng.normal(3.5, 1.0))
    encounter.discharge_datetime = visit_time + timedelta(hours=max(1, ed_hours))

    # Pre-assign a lab tech for this visit's labs
    lab_tech_assignment = assign_staff("lab_collection", "laboratory", roster, rng)
    lab_tech_id = lab_tech_assignment.get("performing_technician", "")

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
            ordered_by=encounter.attending_physician_id,
            status=OrderStatus.PLACED,
        )
        observed = generate_lab_result(test, baseline_values.get(test, 100), rng)
        flag = determine_flag(test, observed, sex=patient.sex)
        order.result = OrderResult(
            result_datetime=visit_time + timedelta(minutes=int(rng.normal(50, 15))),
            performed_by=lab_tech_id,
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
            ordered_by=encounter.attending_physician_id,
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
            ordered_by=encounter.attending_physician_id,
            status=OrderStatus.PLACED,
        ))

    # Vitals
    bv = patient.baseline_vitals
    ed_nurse_id = assign_staff("medication_administration", "emergency_medicine", roster, rng).get("administering_nurse", "")
    vitals = [VitalSignRecord(
        timestamp=visit_time + timedelta(minutes=5),
        temperature_celsius=round(float(rng.normal(36.8, 0.5)), 1),
        heart_rate=int(rng.normal(bv.heart_rate, 10)),
        systolic_bp=int(rng.normal(bv.systolic_bp, 10)),
        diastolic_bp=int(rng.normal(bv.diastolic_bp, 7)),
        respiratory_rate=int(rng.normal(16, 2)),
        spo2=round(float(min(99, rng.normal(97.5, 1))), 1),
        pain_score=int(max(0, min(10, rng.normal(3, 2)))),
        measured_by=ed_nurse_id,
        data_source="manual",
    )]

    # Enrich medication orders + assign encounter_id
    from clinosim.modules.order.engine import enrich_medication_order
    for o in orders:
        if o.order_type == OrderType.MEDICATION:
            enrich_medication_order(o)
        if not o.encounter_id:
            o.encounter_id = encounter.encounter_id

    # ED encounter metadata
    encounter.admit_source = "outp"
    encounter.discharge_disposition = "home"
    encounter.priority = "EM"
    encounter.admitting_physician_id = encounter.attending_physician_id
    encounter.discharging_physician_id = encounter.attending_physician_id

    # Use ICD-10 from encounter YAML (required by FHIR R4)
    icd_code = (protocol or condition).get("icd10_code", "R69")  # R69 = Illness, unspecified
    icd_display = (protocol or condition).get("icd10_display", chief or cond_name)

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
            admission_diagnosis_code=icd_code,
            admission_diagnosis_system="icd-10" if country == "JP" else "icd-10-cm",
            discharge_diagnosis_code=icd_code,
            discharge_diagnosis_system="icd-10" if country == "JP" else "icd-10-cm",
        ),
    )
