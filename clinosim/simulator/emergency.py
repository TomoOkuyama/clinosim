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
    config: object | None = None,
) -> CIFPatientRecord:
    """Simulate an ED visit using YAML protocol if available, else basic."""
    from clinosim.modules.observation.engine import (
        canonical_lab_name,
        determine_flag,
        generate_lab_result,
    )
    from clinosim.modules.physiology.engine import (
        apply_disease_onset,
        derive_lab_values,
        derive_observed_vitals,
        initialize_state,
        medication_flags_from_context,
        scenario_flags_from_protocol,
    )

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
        severity = "moderate"
        ed_hours = float(rng.normal(3.5, 1.0))
    encounter.discharge_datetime = visit_time + timedelta(hours=max(1, ed_hours))
    # AD-65 Bug C fix: persist sampled severity onto the Encounter so the
    # POST_ENCOUNTER triage_enricher (clinosim/modules/triage/engine.py) can read
    # it instead of silently defaulting to "moderate" for every ED encounter
    # (root cause of all-L2-L4, zero-L1/L5 triage_level distribution).
    encounter.severity = severity

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

    # Comorbidity-aware true values via the same physiology path as inpatient (AD-57):
    # a baseline state built from the patient's chronic conditions (CKD → high Cr, etc.),
    # then derive_lab_values. baseline_values is the reference-normal fallback for analytes
    # physiology doesn't model (HbA1c/WBC/CRP etc. resolve via _true_labs first). DET-6.
    from clinosim.modules.observation.engine import BASELINE_LAB_NORMALS
    baseline_values = BASELINE_LAB_NORMALS
    _state = initialize_state(patient.physiological_profile, patient.chronic_conditions,
                              patient.patient_id)
    # Acute-presentation injection (AD-57): fold the ED scenario's physiological impact (by
    # the sampled severity) into the state so BOTH labs and vitals reflect the acute illness
    # (e.g. UTI → WBC/CRP/temp up, gastroenteritis → dehydration), not just the comorbidity
    # baseline. Data-driven from the encounter YAML's optional initial_state_impact, reusing
    # the same physiology entry point as inpatient onset. No new RNG draws (determinism).
    if protocol and protocol.get("initial_state_impact"):
        _state = apply_disease_onset(
            _state, severity, protocol["initial_state_impact"],
            acid_base_type=protocol.get("acid_base_type", "metabolic"),
        )
    _has_dm = any("E11" in (getattr(c, "code", "") or "") for c in patient.chronic_conditions)
    # J5 (Phase 2a): wire all scenario flags (causes_myocardial_injury,
    # causes_vte) through the helper. Pre-Phase-2a, the ED path passed no
    # flag — ED-presentation MI patients had no troponin upshift.
    # Phase 2b (2026-06-24): also merge medication flags (on_warfarin).
    # ED is admit-day; no in-hospital ramp (no MAR / day-into-stay applies) —
    # chronic-only path runs via patient.current_medications.
    _flags = {
        **scenario_flags_from_protocol(protocol),
        **medication_flags_from_context(patient),
    }
    _true_labs = derive_lab_values(_state, sex=patient.sex, age=patient.age, has_diabetes=_has_dm, **_flags)
    # AD-16: per-lab-order sub-RNG so probability skips / noise / timing draws
    # cannot poison the patient master stream when derive_lab_values gains a new
    # analyte (Cl/Ca emission, etc.). See inpatient.py Pass 1 for the parallel
    # fix on the inpatient side.
    from clinosim.simulator.seeding import individual_lab_seed
    for i, lab_spec in enumerate(lab_specs):
        test = lab_spec.get("test", "")
        order_id = f"ORD-{patient.patient_id}-ED-L{i}"
        lab_rng = np.random.default_rng(individual_lab_seed(order_id))
        prob = lab_spec.get("probability", 1.0)
        if lab_rng.random() > prob:
            continue
        # Skip non-quantitative diagnostics (e.g. ECG) misfiled under labs — not lab
        # analytes, must not get a fabricated value (AD-57 cleanup).
        canon = canonical_lab_name(test)
        if canon not in _true_labs and canon not in baseline_values:
            continue
        order = Order(
            order_id=order_id,
            patient_id=patient.patient_id,
            order_type=OrderType.LAB,
            display_name=test, urgency="stat",
            clinical_intent=f"ED workup: {test}",
            ordered_datetime=visit_time + timedelta(minutes=int(lab_rng.normal(10, 5))),
            ordered_by=encounter.attending_physician_id,
            status=OrderStatus.PLACED,
        )
        true_val = _true_labs.get(canon, baseline_values.get(canon, 1.0))
        observed = generate_lab_result(canon, true_val, lab_rng)
        flag = determine_flag(canon, observed, sex=patient.sex)
        order.result = OrderResult(
            result_datetime=visit_time + timedelta(minutes=int(lab_rng.normal(50, 15))),
            performed_by=lab_tech_id,
            lab_name=canon, value=observed,
            unit=get_lab_unit(canon), flag=flag,
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

    # Vitals — physiology-driven via the same derivation path as inpatient (AD-57):
    # true values come from the comorbidity-adjusted state, then measurement noise.
    ed_nurse_id = assign_staff("medication_administration", "emergency_medicine", roster, rng).get("administering_nurse", "")
    vit_time = visit_time + timedelta(minutes=5)
    raw = derive_observed_vitals(_state, patient.baseline_vitals, vit_time, rng)
    # ED presentations are acute → pain skews higher, scaled by inflammation.
    pain = int(max(0, min(10, rng.normal(_state.inflammation_level * 4 + 2, 1.5))))
    vitals = [VitalSignRecord(
        timestamp=vit_time,
        temperature_celsius=round(raw["temperature"], 1),
        heart_rate=int(round(raw["heart_rate"])),
        systolic_bp=int(round(raw["systolic_bp"])),
        diastolic_bp=int(round(raw["diastolic_bp"])),
        respiratory_rate=int(round(raw["respiratory_rate"])),
        spo2=round(raw["spo2"], 1),
        pain_score=pain,
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

    record = CIFPatientRecord(
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

    # POST_ENCOUNTER stage for ED encounters (α-min-2 Task 14 fix)
    # triage_enricher (order=93) populates triage_data; document_enricher (order=95)
    # dispatches ED_NOTE + ED_TRIAGE_NOTE for EMERGENCY encounters.
    # Only fires when config is provided (engine.py passes it; cli test-ed does not).
    if config is not None:
        from clinosim.simulator.enrichers import (
            POST_ENCOUNTER,
            EnricherContext,
            run_stage,
        )
        run_stage(
            POST_ENCOUNTER,
            EnricherContext(
                config=config,
                master_seed=config.random_seed,  # type: ignore[attr-defined]
                records=[record],
                roster=roster,
            ),
        )

    return record
