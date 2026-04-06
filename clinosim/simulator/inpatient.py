"""Inpatient simulation — patient encounter, daily loop, MAR, vitals, etc."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta
from typing import Any

import numpy as np

from clinosim.modules.clinical_course.engine import (
    apply_diagnosis_modifier,
    compute_diagnosis_effectiveness,
    evaluate_complications,
    get_daily_directive,
    natural_recovery_directive,
    select_archetype,
)
from clinosim.modules.diagnosis.engine import (
    get_current_diagnosis_code,
    initialize_differential,
    update_differential,
)
from clinosim.modules.disease.protocol import DiseaseProtocol
from clinosim.modules.encounter.engine import create_inpatient_encounter
from clinosim.modules.observation.engine import determine_flag, generate_lab_result, get_lab_unit
from clinosim.modules.order.engine import (
    calculate_result_time_from_state,
    place_admission_orders,
    place_daily_lab_orders,
)
from clinosim.modules.physiology.engine import (
    apply_disease_onset,
    derive_lab_values,
    derive_vital_signs,
    initialize_state,
    update,
)
from clinosim.modules.population.engine import LifeEvent
from clinosim.modules.procedure.engine import (
    generate_rehab_sessions,
    simulate_surgery,
)
from clinosim.modules.staff.engine import StaffRoster, assign_staff
from clinosim.types.clinical import (
    ClinicalDiagnosis,
    ConditionEvent,
    PhysiologicalState,
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
from clinosim.types.output import CIFPatientRecord
from clinosim.types.patient import PatientProfile

from clinosim.simulator.helpers import (
    _check_discharge_ready,
    _country_to_yaml_key,
    _determine_route,
    _disease_chief_complaint,
    _disease_to_department,
    _evaluate_mortality,
)


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
    is_readmission: bool = False,
    prior_encounter_id: str | None = None,
    readmission_number: int = 0,
    hospital_state: Any = None,
    hospital_ops: dict | None = None,
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
        # Apply minimum severity from protocol (e.g., fractures are at least moderate)
        if protocol.minimum_severity:
            severity_order = ["mild", "moderate", "severe"]
            min_idx = severity_order.index(protocol.minimum_severity) if protocol.minimum_severity in severity_order else 0
            cur_idx = severity_order.index(severity) if severity in severity_order else 0
            if cur_idx < min_idx:
                severity = protocol.minimum_severity

    if forced_archetype:
        archetype = forced_archetype
    else:
        archetype = select_archetype(severity, patient.physiological_profile, rng)

    # Initialize physiological state
    state = initialize_state(patient.physiological_profile, patient.chronic_conditions, patient.patient_id)

    # Readmission: carry over residual state from prior hospitalization
    if is_readmission:
        # Readmitted patients have worse baseline (incomplete recovery from prior stay)
        state.inflammation_level = max(state.inflammation_level, 0.05)
        state.renal_function = min(state.renal_function, 0.9)

    state = apply_disease_onset(state, severity, protocol.initial_state_impact)

    # Mixed condition: superimpose secondary disease's state impact
    secondary_disease_id = None
    if secondary_protocol:
        secondary_disease_id = secondary_protocol.disease_id
        # Secondary disease typically presents at moderate severity
        state = apply_disease_onset(state, "moderate", secondary_protocol.initial_state_impact)

    # Create encounter — realistic admission time pattern
    if protocol.encounter_type == "surgical":
        # Elective surgery: morning admission (8-10)
        adm_hour = int(rng.choice([8, 9, 10], p=[0.3, 0.5, 0.2]))
    elif event.severity > 0.6:
        # Emergency: any hour, peak in evening (ED presentation)
        adm_hour = int(rng.choice(24))
    else:
        # Urgent: daytime bias (9-20)
        adm_hour = int(rng.normal(14, 3))
        adm_hour = max(8, min(22, adm_hour))
    adm_minute = int(rng.integers(0, 60))
    admission_time = datetime(event.timestamp.year, event.timestamp.month, event.timestamp.day,
                               adm_hour, adm_minute)
    chief_complaint = _disease_chief_complaint(protocol)
    encounter = create_inpatient_encounter(
        patient.patient_id, admission_time,
        chief_complaint=chief_complaint,
        visit_number=readmission_number + 1,
    )

    # Staff assignment — department from protocol YAML
    department = _disease_to_department(protocol)
    staff = assign_staff("admission", department, roster, rng)
    attending_id = staff.get("attending_physician", "DR-001")
    encounter.attending_physician_id = attending_id

    # Ward and bed assignment
    ward_floor = int(rng.integers(3, 7))  # floors 3-6
    ward_wing = str(rng.choice(["E", "W"]))
    encounter.ward_id = f"{ward_floor}{ward_wing}"
    encounter.bed_number = f"{ward_floor}{int(rng.integers(1, 30)):02d}-{int(rng.integers(1, 5))}"

    # LOS (country-specific)
    country_key = _country_to_yaml_key(config.country)
    los_by_country = protocol.target_los.get(country_key) or protocol.target_los.get("japan", {})
    los_cfg = los_by_country.get(severity, {"mean": 14, "sd": 4, "min": 5, "max": 30})
    target_los = int(max(los_cfg.get("min", 5), min(los_cfg.get("max", 30), rng.normal(los_cfg["mean"], los_cfg["sd"]))))
    # Archetypes with treatment changes need minimum LOS to reach the change day
    if archetype in ("treatment_resistant", "plateau", "gradual_deterioration", "sudden_deterioration"):
        arc_data = (protocol.course_archetypes or {}).get(archetype, {})
        treatment_mods = arc_data.get("treatment_modifications", {})
        if treatment_mods:
            mod_days = [int(k.split("_")[1]) for k in treatment_mods if k.startswith("day_")]
            if mod_days:
                target_los = max(target_los, max(mod_days) + 2)

    # Admission orders
    admission_orders = place_admission_orders(
        protocol.model_dump(), patient.patient_id, encounter.encounter_id,
        admission_time, country=country_key, rng=rng,
    )
    for o in admission_orders:
        o.ordered_by = attending_id

    # Home medication orders (chronic condition continuation)
    home_med_orders, chronic_monitoring = _generate_home_medication_orders(
        patient, encounter.encounter_id, admission_time, attending_id, rng,
    )
    admission_orders.extend(home_med_orders)

    # Tracking
    procedures, rehab_sessions = [], []
    icu_transferred, death_occurred = False, False

    # Surgery (protocol-driven: requires_surgery flag in YAML)
    if protocol.requires_surgery:
        proc, impacts = simulate_surgery(patient, disease_id, encounter.encounter_id,
                                          admission_time, protocol, rng, config.country)
        procedures.append(proc)
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
    protocol_min_los = los_cfg.get("min", 3)
    loop_result = _run_daily_loop(
        state, patient, disease_id, protocol, archetype, differential,
        admission_orders, admission_time, target_los, has_diabetes,
        healthcare, roster, rng,
        chronic_monitoring=chronic_monitoring,
        country_key=country_key,
        min_los=protocol_min_los,
        hospital_state=hospital_state,
        hospital_ops=hospital_ops,
    )

    # Unpack results
    all_orders = loop_result["orders"]
    all_lab_results = loop_result["lab_results"]
    all_vitals = loop_result["vitals"]
    all_mars = loop_result["mars"]
    all_io = loop_result.get("io_records", [])
    all_adl = loop_result.get("adl_assessments", [])
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
    discharge_rx = _build_discharge_rx(patient, disease_id, protocol, attending_id, rng, country_key=country_key) if not death_occurred else None

    # Encounter completion
    encounter.status = EncounterStatus.COMPLETED
    # Discharge time: morning (10-12) for planned discharge, any time for death
    dc_hour = 0 if death_occurred else int(rng.normal(11, 1.5))
    dc_hour = max(9, min(16, dc_hour)) if not death_occurred else 0
    encounter.discharge_datetime = admission_time + timedelta(days=actual_los, hours=dc_hour)

    return CIFPatientRecord(
        patient=patient, encounters=[encounter], orders=all_orders,
        vital_signs=all_vitals, lab_results=all_lab_results,
        condition_event=condition_event, clinical_diagnosis=clinical_diagnosis,
        complications_occurred=complications_occurred,
        procedures=procedures, rehab_sessions=rehab_sessions,
        medication_administrations=all_mars,
        intake_output_records=all_io,
        adl_assessments=all_adl,
        discharge_prescription=discharge_rx,
        icu_transferred=icu_transferred, deceased=death_occurred,
        death_day=actual_los if death_occurred else None,
        is_readmission=is_readmission,
        prior_encounter_id=prior_encounter_id,
        readmission_number=readmission_number,
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
    chronic_monitoring: list[dict] | None = None,
    country_key: str = "japan",
    min_los: int = 3,
    hospital_state: Any = None,
    hospital_ops: dict | None = None,
) -> dict:
    """Run the day-by-day simulation loop. Returns all generated data."""

    all_orders = list(admission_orders)
    all_lab_results: list[OrderResult] = []
    all_vitals: list[VitalSignRecord] = []
    all_mars: list[MedicationAdministration] = []
    all_io: list = []
    all_adl: list = []
    state_history = [deepcopy(state)]
    active_complications: set[str] = set()
    complications_occurred: list[str] = []
    death_occurred = False
    icu_transferred = False

    # Determine severity string for natural recovery scaling
    severity_str = "moderate"  # default
    for s in ("severe", "moderate", "mild"):
        los_data = (protocol.target_los.get(country_key) or {}).get(s)
        if los_data and abs(target_los - los_data.get("mean", 14)) < 5:
            severity_str = s
            break

    for day in range(target_los):
        # State update with diagnosis-treatment feedback
        directive = get_daily_directive(
            archetype, day, patient.physiological_profile,
            protocol_archetypes=protocol.course_archetypes or None,
            age=patient.age, rng=rng,
        )

        # Phase 1: Dampen recovery if diagnosis is wrong
        dx_confidence = 0.0
        working_dx = None
        if differential.top_candidate:
            dx_confidence = differential.top_candidate.probability
            working_dx = differential.top_candidate.disease_code
        dx_difficulty = (protocol.diagnostic or {}).get("diagnostic_difficulty", 0.3)
        effectiveness = compute_diagnosis_effectiveness(
            working_dx, disease_id, dx_confidence, day,
            diagnostic_difficulty=dx_difficulty,
        )
        directive = apply_diagnosis_modifier(
            directive, effectiveness,
            current_volume=state.volume_status,
            current_ph=state.ph_status,
        )

        # Phase 2: Natural recovery (small baseline healing)
        nat_directive = natural_recovery_directive(
            day, disease_id, severity_str, patient.physiological_profile,
        )
        for var, delta in nat_directive.changes.items():
            directive.changes[var] = directive.changes.get(var, 0.0) + delta

        state = update(state, directive, timedelta(days=1))
        state_history.append(deepcopy(state))

        # Daily lab orders (from Day 1) with context-dependent frequency
        if day >= 1:
            # Morning lab draw: 05:30-07:00 with jitter
            lab_hour = 6
            lab_min = int(rng.integers(0, 45))  # 06:00-06:45
            if rng.random() < 0.2:
                lab_hour = 5
                lab_min = int(rng.integers(30, 60))  # 05:30-06:00
            lab_time = datetime(
                admission_time.year, admission_time.month, admission_time.day,
                lab_hour, lab_min,
            ) + timedelta(days=day)

            # Context-dependent lab frequency modulation
            freq_mod = healthcare.lab_frequency_multiplier
            # Near discharge: reduce routine labs
            if day >= target_los - 2 and state.inflammation_level < 0.1:
                freq_mod *= 0.5
            # Weekend: reduce non-urgent labs
            if lab_time.weekday() >= 5:  # Saturday/Sunday
                freq_mod *= 0.7
            # Stable patient: reduce after first week
            if day >= 7 and state.inflammation_level < 0.15:
                freq_mod *= 0.8

            daily_orders = place_daily_lab_orders(
                protocol.model_dump(), patient.patient_id, "", day, lab_time,
                freq_mod, rng,
            )
            all_orders.extend(daily_orders)

        # Chronic condition monitoring labs (additional to disease protocol)
        if chronic_monitoring and day >= 1:
            chronic_lab_orders = _place_chronic_monitoring_orders(
                chronic_monitoring, patient.patient_id, day, admission_time, rng,
            )
            all_orders.extend(chronic_lab_orders)

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
                # Pre-analytical issues: specimen rejection (~2%), hemolysis (~3% for K/LDH)
                if rng.random() < 0.02:
                    order.status = OrderStatus.CANCELLED
                    continue  # specimen lost/rejected
                if order.display_name in ("K", "LDH") and rng.random() < 0.03:
                    # Hemolyzed sample → falsely elevated K/LDH, flagged
                    result_time = calculate_result_time_from_state(order, hospital_state, hospital_ops or {}, rng)
                    hemolyzed_val = true_labs[order.display_name] * float(rng.uniform(1.2, 1.8))
                    lab_tech = assign_staff("lab_result", "", roster, rng).get("performing_technician", "TECH-001")
                    order.result = OrderResult(
                        result_datetime=result_time, performed_by=lab_tech,
                        lab_name=order.display_name, value=round(hemolyzed_val, 1),
                        unit=get_lab_unit(order.display_name), flag="H*",
                    )
                    order.status = OrderStatus.RESULTED
                    all_lab_results.append(order.result)
                    continue

                result_time = calculate_result_time_from_state(order, hospital_state, hospital_ops or {}, rng)
                observed = generate_lab_result(order.display_name, true_labs[order.display_name], rng)
                flag = determine_flag(order.display_name, observed, sex=patient.sex)
                lab_tech = assign_staff("lab_result", "", roster, rng).get("performing_technician", "TECH-001")
                order.result = OrderResult(
                    result_datetime=result_time, performed_by=lab_tech,
                    lab_name=order.display_name, value=observed,
                    unit=get_lab_unit(order.display_name), flag=flag,
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
            start_meds = mod.get("start", {}).get(country_key, mod.get("start", []))
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

        # Medication administration (MAR)
        mars_today = _generate_mar(patient, all_orders, day, admission_time, roster, rng)
        all_mars.extend(mars_today)

        # Diet order (only when diet changes: NPO → clear liquid → soft → regular)
        if day == 0:
            diet = "NPO"
        elif day == 1 and state.inflammation_level > 0.3:
            diet = "clear_liquid"
        elif state.inflammation_level > 0.2:
            diet = "soft_diet"
        else:
            diet = "regular_diet"
        prev_diet = getattr(_generate_vitals, '_prev_diet', {}).get(patient.patient_id, "")
        if diet != prev_diet:
            all_orders.append(Order(
                order_id=f"ORD-{patient.patient_id}-DIET-D{day}",
                patient_id=patient.patient_id,
                order_type=OrderType.DIET,
                display_name=diet,
                urgency="routine",
                clinical_intent=f"Day {day} diet: {diet}",
                ordered_datetime=admission_time + timedelta(days=day, hours=7),
                status=OrderStatus.PLACED,
            ))
            if not hasattr(_generate_vitals, '_prev_diet'):
                _generate_vitals._prev_diet = {}
            _generate_vitals._prev_diet[patient.patient_id] = diet

        # Vitals
        vitals_today = _generate_vitals(state, patient, day, admission_time, rng)
        all_vitals.extend(vitals_today)

        # Daily I/O record
        io_record = _generate_daily_io(state, patient, day, admission_time, rng)
        all_io.append(io_record)

        # ADL assessment (admission, weekly, discharge approach)
        adl = _generate_adl_assessment(state, patient, day, admission_time, rng)
        if adl:
            all_adl.append(adl)

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

        # Mortality (disease-specific rate from YAML benchmarks)
        benchmark_mortality = (protocol.outcome_benchmarks.get(country_key, {})
                               .get("in_hospital_mortality", 0.0))
        if _evaluate_mortality(
            state, patient, severity=severity_str, day=day, rng=rng,
            disease_mortality_rate=benchmark_mortality,
            target_los=target_los,
        ):
            death_occurred = True
            break

        # Early discharge: if state-based criteria met before target_los
        if day >= min_los and not death_occurred:
            if _check_discharge_ready(state, day, country_key):
                break  # actual_los = day + 1

    actual_los = day + 1
    return {
        "orders": all_orders, "lab_results": all_lab_results, "vitals": all_vitals,
        "mars": all_mars, "io_records": all_io, "adl_assessments": all_adl,
        "state_history": state_history,
        "complications": complications_occurred, "death_occurred": death_occurred,
        "icu_transferred": icu_transferred, "differential": differential,
        "actual_los": actual_los,
    }


# ============================================================
# Medication Administration Records (MAR)
# ============================================================
# Home medications and chronic monitoring
# ============================================================

def _generate_home_medication_orders(
    patient: PatientProfile,
    encounter_id: str,
    admission_time: datetime,
    attending_id: str,
    rng: np.random.Generator,
) -> tuple[list[Order], list[dict]]:
    """Generate medication orders for home meds (chronic condition continuation).

    Returns:
        (medication_orders, chronic_monitoring_specs)
    """
    from clinosim.locale.loader import load_chronic_medications
    chronic_meds = load_chronic_medications()

    orders: list[Order] = []
    monitoring: list[dict] = []
    med_idx = 0

    for condition in patient.chronic_conditions:
        code = condition.code
        spec = chronic_meds.get(code)
        if not spec:
            continue

        # Home medications (with renal dose adjustment)
        has_ckd = any(c.code.startswith("N18") for c in patient.chronic_conditions)
        renal_reserve = patient.physiological_profile.renal_reserve if hasattr(patient, "physiological_profile") else 1.0

        for med in spec.get("medications", []):
            prob = med.get("probability", 1.0)
            if prob < 1.0 and rng.random() > prob:
                continue

            drug_name = med["drug"]
            intent = f"Home medication (continue): {code} - {drug_name}"

            # Renal dose adjustment for CKD patients
            if has_ckd and renal_reserve < 0.5:
                renal_drugs = ["Metformin", "Enoxaparin", "Enalapril", "Candesartan",
                               "Alendronate", "Celecoxib"]
                if any(rd.lower() in drug_name.lower() for rd in renal_drugs):
                    if "Metformin" in drug_name and renal_reserve < 0.3:
                        intent += " [HELD - eGFR<30]"
                        continue  # contraindicated
                    elif "Celecoxib" in drug_name:
                        intent += " [HELD - renal impairment]"
                        continue
                    else:
                        intent += " [dose reduced for renal impairment]"

            order = Order(
                order_id=f"ORD-{patient.patient_id}-HM-{med_idx:02d}",
                encounter_id=encounter_id,
                patient_id=patient.patient_id,
                order_type=OrderType.MEDICATION,
                order_code="",
                display_name=drug_name,
                urgency="routine",
                clinical_intent=intent,
                ordered_datetime=admission_time + timedelta(minutes=60),
                ordered_by=attending_id,
                status=OrderStatus.PLACED,
            )
            orders.append(order)
            med_idx += 1

        # Monitoring specs (passed to daily loop)
        for mon in spec.get("monitoring", []):
            monitoring.append(mon)

    return orders, monitoring


def _place_chronic_monitoring_orders(
    monitoring: list[dict],
    patient_id: str,
    day: int,
    admission_time: datetime,
    rng: np.random.Generator,
) -> list[Order]:
    """Place additional lab orders for chronic condition monitoring."""
    orders: list[Order] = []

    for i, mon in enumerate(monitoring):
        freq = mon.get("frequency", "daily")

        # Frequency-based scheduling
        if freq == "every_3_days" and day % 3 != 0:
            continue
        if freq == "qid":
            # Multiple times per day — handled differently (monitoring, not standard lab)
            # Generate separate orders at each time
            times = mon.get("times", [6, 11, 17, 21])
            for t_idx, hour in enumerate(times):
                order_time = datetime(
                    admission_time.year, admission_time.month, admission_time.day,
                    hour, 0,
                ) + timedelta(days=day)
                if order_time < admission_time:
                    continue
                orders.append(Order(
                    order_id=f"ORD-{patient_id}-CM-D{day:02d}-{i:02d}-{t_idx}",
                    encounter_id="",
                    patient_id=patient_id,
                    order_type=OrderType.LAB,
                    order_code="",
                    display_name=mon["test"],
                    urgency="routine",
                    clinical_intent=mon.get("intent", f"Chronic monitoring: {mon['test']}"),
                    ordered_datetime=order_time,
                    ordered_by="",
                    status=OrderStatus.PLACED,
                ))
            continue

        if freq == "tid":
            times = [8, 14, 20]
            for t_idx, hour in enumerate(times):
                order_time = datetime(
                    admission_time.year, admission_time.month, admission_time.day,
                    hour, 0,
                ) + timedelta(days=day)
                if order_time < admission_time:
                    continue
                orders.append(Order(
                    order_id=f"ORD-{patient_id}-CM-D{day:02d}-{i:02d}-{t_idx}",
                    encounter_id="",
                    patient_id=patient_id,
                    order_type=OrderType.LAB,
                    order_code="",
                    display_name=mon["test"],
                    urgency="routine",
                    clinical_intent=mon.get("intent", f"Chronic monitoring: {mon['test']}"),
                    ordered_datetime=order_time,
                    ordered_by="",
                    status=OrderStatus.PLACED,
                ))
            continue

        # Default: daily at 06:00
        order_time = datetime(
            admission_time.year, admission_time.month, admission_time.day, 6, 0,
        ) + timedelta(days=day)
        orders.append(Order(
            order_id=f"ORD-{patient_id}-CM-D{day:02d}-{i:02d}",
            encounter_id="",
            patient_id=patient_id,
            order_type=OrderType.LAB,
            order_code="",
            display_name=mon["test"],
            urgency="routine",
            clinical_intent=mon.get("intent", f"Chronic monitoring: {mon['test']}"),
            ordered_datetime=order_time,
            ordered_by="",
            status=OrderStatus.PLACED,
        ))

    return orders


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

def _generate_adl_assessment(
    state: PhysiologicalState,
    patient: PatientProfile,
    day: int,
    admission_time: datetime,
    rng: np.random.Generator,
) -> dict | None:
    """Generate ADL (Barthel Index) assessment. Done on admission, weekly, and discharge."""
    from clinosim.types.encounter import ADLAssessment

    # ADL assessed on admission (day 0), weekly (day 7, 14...), and approaching discharge
    if day != 0 and day % 7 != 0:
        return None

    # Base score depends on age and clinical state
    age = patient.age
    base = 100
    if age >= 85:
        base -= 20
    elif age >= 75:
        base -= 10

    # Acute illness reduces ADL
    infl_penalty = int(state.inflammation_level * 30)
    perf_penalty = int((1.0 - state.perfusion_status) * 20)
    renal_penalty = int((1.0 - state.renal_function) * 10)

    # Day 0: worst ADL (acute admission)
    if day == 0:
        total = max(0, base - infl_penalty - perf_penalty - renal_penalty - 15)
    else:
        # Gradual recovery
        recovery = min(day * 3, 30)  # up to +30 over time
        total = max(0, min(100, base - infl_penalty - perf_penalty + recovery))

    total = int(rng.normal(total, 5))
    total = max(0, min(100, total))

    # Distribute across components proportionally
    ratio = total / 100.0
    return ADLAssessment(
        date=(admission_time + timedelta(days=day)).date(),
        barthel_score=total,
        feeding=int(10 * min(1, ratio + 0.1)),
        bathing=int(5 * ratio),
        grooming=int(5 * min(1, ratio + 0.1)),
        dressing=int(10 * ratio),
        bowel_control=int(10 * min(1, ratio + 0.2)),
        bladder_control=int(10 * min(1, ratio + 0.15)),
        toilet_use=int(10 * ratio),
        transfers=int(15 * ratio),
        mobility=int(15 * ratio),
        stairs=int(10 * max(0, ratio - 0.2)),
    )


def _generate_daily_io(
    state: PhysiologicalState,
    patient: PatientProfile,
    day: int,
    admission_time: datetime,
    rng: np.random.Generator,
) -> dict:
    """Generate daily intake/output record."""
    from clinosim.types.encounter import IntakeOutputRecord

    # IV fluid: higher in early days, less as patient improves
    if day <= 2:
        iv = int(rng.normal(1500, 300))  # aggressive hydration
    elif state.volume_status < -0.2:
        iv = int(rng.normal(1200, 200))  # dehydrated
    else:
        iv = int(rng.normal(500, 200))  # maintenance

    # Oral intake: improves as patient recovers
    if day == 0:
        oral = int(rng.normal(200, 100))  # NPO or minimal
    elif state.inflammation_level > 0.3:
        oral = int(rng.normal(500, 200))  # poor appetite
    else:
        oral = int(rng.normal(1200, 300))  # recovering

    # Urine output: correlates with renal function and hydration
    base_urine = 1500 * state.renal_function
    urine_sd = max(100, base_urine * 0.2)  # SD proportional to base
    urine = int(max(50, rng.normal(base_urine, urine_sd)))  # min 50ml (anuria threshold)

    # Drain (post-surgical only, simplified)
    drain = 0

    iv = max(0, iv)
    oral = max(0, oral)
    total_in = iv + oral
    total_out = urine + drain
    net = total_in - total_out

    io_date = (admission_time + timedelta(days=day)).date()
    return IntakeOutputRecord(
        date=io_date,
        intake_iv_ml=iv, intake_oral_ml=oral,
        output_urine_ml=urine, output_drain_ml=drain,
        net_balance_ml=net,
    )


def _generate_vitals(
    state: PhysiologicalState,
    patient: PatientProfile,
    day: int,
    admission_time: datetime,
    rng: np.random.Generator,
) -> list[VitalSignRecord]:
    """Generate vital sign measurements for this day with context-dependent frequency."""
    vitals: list[VitalSignRecord] = []

    # Measurement schedule depends on acuity
    if state.perfusion_status < 0.5 or state.inflammation_level > 0.5:
        # Unstable: q4h
        hours = [2, 6, 10, 14, 18, 22]
    elif day <= 2:
        # Early admission: q6h
        hours = [0, 6, 12, 18]
    elif state.inflammation_level < 0.1 and day >= 7:
        # Stable, late stay: bid
        hours = [6, 18]
    else:
        # Standard: tid
        hours = [6, 14, 18]

    for hour in hours:
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

        # Pain score (NRS 0-10): correlates with inflammation and surgical status
        base_pain = state.inflammation_level * 4  # inflammation → pain
        if day <= 2:
            base_pain += 2  # acute phase
        pain = max(0, min(10, int(rng.normal(base_pain, 1.5))))

        # Brief nursing note (context-dependent)
        note_parts = []
        if raw["temperature"] >= 38.0:
            note_parts.append("febrile")
        if pain >= 5:
            note_parts.append(f"pain {pain}/10, analgesic administered")
        elif pain >= 3:
            note_parts.append(f"mild pain {pain}/10")
        if raw["spo2"] < 93:
            note_parts.append(f"SpO2 low, O2 adjusted")
        if state.inflammation_level < 0.1 and day >= 3:
            note_parts.append("improving, appetite good")
        if day == 0:
            note_parts.append("admission assessment completed")
        nursing_note = ". ".join(note_parts) + "." if note_parts else ""

        vitals.append(VitalSignRecord(
            timestamp=actual_time,
            temperature_celsius=round(raw["temperature"], 1),
            heart_rate=int(round(raw["heart_rate"])),
            systolic_bp=int(round(raw["systolic_bp"])),
            diastolic_bp=int(round(raw["diastolic_bp"])),
            respiratory_rate=int(round(raw["respiratory_rate"])),
            spo2=round(raw["spo2"], 1),
            pain_score=pain,
            nursing_note=nursing_note,
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
    country_key: str = "japan",
) -> PrescriptionRecord:
    """Build discharge prescription from protocol."""
    items: list[dict] = []

    discharge_drugs = protocol.drugs.get("discharge_oral", {}).get(country_key, [])
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
    # Ward/bed for unknown condition patients
    ward_floor = int(rng.integers(3, 7))
    encounter.ward_id = f"{ward_floor}{'EW'[int(rng.integers(0, 2))]}"
    encounter.bed_number = f"{ward_floor}{int(rng.integers(1, 30)):02d}-{int(rng.integers(1, 5))}"
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
                result_time = calculate_result_time_from_state(order, None, {}, rng)  # unknown condition: no hospital state
                observed = generate_lab_result(order.display_name, true_labs[order.display_name], rng)
                flag = determine_flag(order.display_name, observed, sex=patient.sex)
                tech_id = assign_staff("lab_result", "", roster, rng).get("performing_technician", "TECH-001")
                order.result = OrderResult(
                    result_datetime=result_time, performed_by=tech_id,
                    lab_name=order.display_name, value=observed,
                    unit=get_lab_unit(order.display_name), flag=flag,
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
