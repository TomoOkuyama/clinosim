"""Inpatient simulation — patient encounter, daily loop, MAR, vitals, etc."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta
from typing import Any

import numpy as np

from clinosim.codes import system_key_for
from clinosim.codes.hl7_encounter import ActPriority, AdmitSource, DischargeDisposition
from clinosim.modules._shared import MED_STOP_ORDER_ID_MARKER, sanitize_id_token
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
from clinosim.modules.diagnosis.nonspecific_codes import UNRESOLVED_DIAGNOSIS_ICD
from clinosim.modules.disease.acuity import (
    EMERGENCY_PRIORITY_DISEASES,
)
from clinosim.modules.disease.localization import target_los_config
from clinosim.modules.disease.protocol import DiseaseProtocol
from clinosim.modules.disease.severity import category_from_score
from clinosim.modules.encounter.engine import create_inpatient_encounter
from clinosim.modules.observation.engine import (
    canonical_lab_name,
    determine_flag,
    generate_lab_result,
    get_lab_unit,
    lab_panel_components,
)
from clinosim.modules.observation.pre_analytical import (
    HEMOLYSIS_LIFT_RANGE,
    HEMOLYSIS_PRONE_LABS,
    HEMOLYSIS_RATE,
    SPECIMEN_REJECTION_RATE,
)
from clinosim.modules.order.engine import (
    calculate_result_time_from_state,
    place_admission_orders,
    place_daily_lab_orders,
    place_imaging_orders,
)
from clinosim.modules.order.treatment_classifier import (
    classify_encounter_treatment,
    classify_escalation_treatment,
)
from clinosim.modules.physiology.engine import (
    apply_disease_onset,
    apply_state_delta,
    derive_lab_values,
    initialize_state,
    medication_flags_from_context,
    scenario_flags_from_protocol,
    update,
)
from clinosim.modules.population.engine import LifeEvent
from clinosim.modules.procedure.engine import (
    generate_bedside_procedures,
    generate_rehab_sessions,
    simulate_surgery,
)
from clinosim.modules.staff.engine import (
    FALLBACK_NURSE_ID,
    FALLBACK_PHYSICIAN_ID,
    FALLBACK_TECH_ID,
    StaffRoster,
    assign_staff,
)
from clinosim.seeding import individual_lab_seed, panel_specimen_seed
from clinosim.simulator.discharge_rx import build_discharge_rx
from clinosim.simulator.helpers import (  # noqa: I001
    _check_discharge_ready,
    _country_to_yaml_key,
    _disease_chief_complaint,
    _disease_chief_complaint_ja,
    _disease_to_department,
    _evaluate_mortality,
)

# Backwards-compat re-exports (Issue #552 PR C). The 3 medication-related
# per-day generators moved to `clinosim/simulator/medication_pipeline.py`.
# Existing call sites in `_run_daily_loop` (and `_simulate_unknown_condition`
# still in this file on this branch) resolve via these re-imports.
from clinosim.simulator.medication_pipeline import (  # noqa: E402, F401
    _generate_home_medication_orders,
    _generate_mar,
    _place_chronic_monitoring_orders,
)

# Backwards-compat re-export (Issue #552 PR D). `_simulate_unknown_condition`
# was moved to `clinosim/simulator/unknown_condition.py`; the re-export keeps
# existing `from clinosim.simulator.inpatient import _simulate_unknown_condition`
# imports resolving without touching call sites in the same PR.
from clinosim.simulator.unknown_condition import _simulate_unknown_condition  # noqa: E402, F401

# Backwards-compat re-exports (Issue #552 PR B). The vitals family (5
# functions + 2 supporting frozensets) moved to
# `clinosim/simulator/vitals_pipeline.py`. Existing call sites in
# `_run_daily_loop` still resolve via these re-imports; new call sites
# should import directly from `vitals_pipeline`.
from clinosim.simulator.vitals_pipeline import (  # noqa: E402, F401
    _NEURO_DISEASES,
    _RESPIRATORY_DISEASES,
    _generate_adl_assessment,
    _generate_daily_io,
    _generate_vitals,
    _loc_for,
    _make_raw,
    _o2_for,
)
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
    VitalSignRecord,
)
from clinosim.types.output import CIFPatientRecord
from clinosim.types.patient import PatientProfile

# ============================================================
# Patient simulation
# ============================================================


def _planned_discharge_datetime(admission_time: datetime, actual_los: int, dc_hour: int) -> datetime:
    """Discharge timestamp for a planned (non-death) discharge.

    The discharge date is `admission_date + actual_los`, and the hour is set
    absolutely from `dc_hour` (typically clamped to 09-16 for business-hour
    discharge). The minute is preserved from admission_time so patients do
    not all land on the same minute.

    Extracted from `_simulate_patient` (Issue #468) so the invariant can be
    unit-tested. The pre-fix code added `dc_hour` as an offset to
    admission_time, which rolled afternoon admissions past midnight and
    silently defeated the clamp.
    """
    return (admission_time + timedelta(days=actual_los)).replace(hour=dc_hour, minute=admission_time.minute)


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
        # Canonical category<->score boundary (FP-SEV-MODEL). minimum_severity is
        # already applied at sampling time (disease.severity.sample_severity), so no
        # local re-clamp is needed — the sampled score already respects the minimum.
        severity = category_from_score(event.severity)

    if forced_archetype:
        archetype = forced_archetype
    else:
        archetype = select_archetype(
            severity,
            patient.physiological_profile,
            rng,
            protocol_archetypes=protocol.course_archetypes or None,
            protocol_modifiers=protocol.archetype_modifiers or None,
            patient=patient,
        )

    # Initialize physiological state
    state = initialize_state(patient.physiological_profile, patient.chronic_conditions, patient.patient_id)

    # Readmission: carry over residual state from prior hospitalization
    if is_readmission:
        # Readmitted patients have worse baseline (incomplete recovery from prior stay)
        state.inflammation_level = max(state.inflammation_level, 0.05)
        state.renal_function = min(state.renal_function, 0.9)

    state = apply_disease_onset(state, severity, protocol.initial_state_impact, acid_base_type=protocol.acid_base_type)

    # Scenario-implied chronic glycemic control (e.g. DKA/HHS imply long-standing poor
    # control). Overrides the patient's sampled glycemic_control so HbA1c is coherently high
    # even for new-onset diabetes. Persists through the stay (not an acute axis). AD-57.
    if protocol.chronic_glycemic_control is not None:
        state.glycemic_control = protocol.chronic_glycemic_control

    # Mixed condition: superimpose secondary disease's state impact
    secondary_disease_id = None
    if secondary_protocol:
        secondary_disease_id = secondary_protocol.disease_id
        # Secondary disease typically presents at moderate severity
        state = apply_disease_onset(
            state, "moderate", secondary_protocol.initial_state_impact, acid_base_type=secondary_protocol.acid_base_type
        )

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
    admission_time = datetime(event.timestamp.year, event.timestamp.month, event.timestamp.day, adm_hour, adm_minute)
    state.timestamp = admission_time
    chief_complaint = _disease_chief_complaint(protocol, country=config.country)
    encounter = create_inpatient_encounter(
        patient.patient_id,
        admission_time,
        chief_complaint=chief_complaint,
        visit_number=readmission_number + 1,
    )
    # Issue #360 G1 (iris4h-ai 2026-07-22): stash JP chief complaint alongside
    # so JP FHIR emitter has a Japanese fallback for Encounter.reasonCode.text
    # when ICD-10 code_lookup can't resolve a Japanese display.
    encounter.chief_complaint_ja = _disease_chief_complaint_ja(protocol)
    # β-JP-1 chain 1a (spec §2a): persist the selected severity + archetype on
    # the Encounter so Stage 2 narrative generation reads them from structural
    # CIF (they were previously in scope here but never written → every
    # narrative rendered severity-/archetype-agnostic).
    encounter.severity = severity
    encounter.clinical_course_archetype = archetype

    # Department resolution: granular YAML specialty → hospital's available department
    from clinosim.simulator.helpers import pick_ward, resolve_department

    granular_dept = _disease_to_department(protocol)
    department = resolve_department(granular_dept, hospital_ops)
    encounter.department_id = department
    staff = assign_staff("admission", department, roster, rng)
    attending_id = staff.get("attending_physician", FALLBACK_PHYSICIAN_ID)
    encounter.attending_physician_id = attending_id

    # Ward assignment from hospital config
    encounter.ward_id = pick_ward(department, hospital_ops, rng)
    # Bed number from hospital ward_capacity (valid range for this ward)
    ward_cap = (hospital_ops or {}).get("ward_capacity", {}).get(encounter.ward_id, 10)
    bed_idx = int(rng.integers(1, ward_cap + 1))
    encounter.bed_number = f"{encounter.ward_id}-{bed_idx:02d}"

    # `country_key` is still needed downstream for drug-block lookups etc.
    country_key = _country_to_yaml_key(config.country)
    # LOS (country-specific) — canonical resolver, Issue #550.
    # `target_los_config` returns None when the protocol has no entry for
    # (country, severity); fall back to the historical wide-Normal default
    # for the sampler.
    los_cfg = target_los_config(protocol, config.country, severity) or {
        "mean": 14,
        "sd": 4,
        "min": 5,
        "max": 30,
    }
    target_los = int(
        max(los_cfg.get("min", 5), min(los_cfg.get("max", 30), rng.normal(los_cfg["mean"], los_cfg["sd"])))
    )  # noqa: E501
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
        protocol.model_dump(),
        patient.patient_id,
        encounter.encounter_id,
        admission_time,
        country=country_key,
        rng=rng,
        ordered_by=attending_id,
    )

    # Imaging orders from disease YAML imaging_orders[] (Tier 1 #2 PR1).
    # Counter is threaded across admission (day=0) + daily loop (day>=1) to
    # guarantee unique order_ids within the encounter.
    imaging_seq_counter: dict[str, int] = {"I": 0}
    adm_imaging = place_imaging_orders(
        protocol,
        encounter.encounter_id,
        patient.patient_id,
        admission_time,
        day_index=0,
        severity=severity,
        rng=rng,
        sequence_counter=imaging_seq_counter,
    )
    admission_orders.extend(adm_imaging)

    # Home medication orders (chronic condition continuation)
    home_med_orders, chronic_monitoring = _generate_home_medication_orders(
        patient,
        encounter.encounter_id,
        admission_time,
        attending_id,
        rng,
        state=state,
        disease_id=disease_id,
        protocol=protocol,
    )
    admission_orders.extend(home_med_orders)

    # Tracking
    procedures, rehab_sessions = [], []
    icu_transferred, death_occurred = False, False

    # Surgery (protocol-driven: requires_surgery flag in YAML)
    if protocol.requires_surgery:
        # Pick a surgeon and anesthesiologist from the roster
        surgeons = [m for m in roster.members if m.role == "physician"]
        surgeon_id = str(rng.choice(surgeons).staff_id) if surgeons else attending_id
        anes_id = str(rng.choice(surgeons).staff_id) if surgeons else attending_id
        operating_rooms = int((hospital_ops or {}).get("resource_capacity", {}).get("operating_rooms", 2))
        proc, impacts = simulate_surgery(
            patient,
            disease_id,
            encounter.encounter_id,
            admission_time,
            protocol,
            rng,
            config.country,
            surgeon_id=surgeon_id,
            anesthesiologist_id=anes_id,
            operating_rooms=operating_rooms,
        )
        procedures.append(proc)
        for var, delta in impacts.items():
            apply_state_delta(state, var, delta)
        rehab_sessions = generate_rehab_sessions(
            patient.patient_id,
            encounter.encounter_id,
            proc.start_datetime,
            target_los,
            rng,
            config.country,
        )

    # Bedside / routine procedures (disease-driven rules)
    bedside = generate_bedside_procedures(
        patient.patient_id,
        encounter.encounter_id,
        disease_id,
        admission_time,
        severity,
        rng,
        config.country,
    )
    procedures.extend(bedside)

    # Apply state impacts from bedside procedures (e.g., blood transfusion)
    for proc in bedside:
        if proc.procedure_type == "blood_transfusion":
            # Each unit of RBC raises Hgb ~1 g/dL → anemia_level -0.07 per unit
            # Assume 1-2 units per transfusion event
            state.anemia_level = max(0.0, state.anemia_level - 0.15)
            state.volume_status = min(1.0, state.volume_status + 0.05)

    # Differential diagnosis
    protocol_diagnostic = protocol.diagnostic if hasattr(protocol, "diagnostic") else {}
    differential = initialize_differential(disease_id, patient.age, protocol_diagnostic=protocol_diagnostic)

    # Daily simulation loop
    has_diabetes = any(c.code.startswith("E11") for c in patient.chronic_conditions)
    # `target_los_config` (Issue #550) returns dict[str, float]; `min_los` param
    # is typed `int`. Cast at the boundary rather than widening the param type.
    protocol_min_los = int(los_cfg.get("min", 3))
    loop_result = _run_daily_loop(
        state,
        patient,
        disease_id,
        protocol,
        archetype,
        differential,
        admission_orders,
        admission_time,
        target_los,
        has_diabetes,
        healthcare,
        roster,
        rng,
        chronic_monitoring=chronic_monitoring,
        country_key=country_key,
        min_los=protocol_min_los,
        hospital_state=hospital_state,
        hospital_ops=hospital_ops,
        attending_id=attending_id,
        encounter_id=encounter.encounter_id,
        department=department,
        severity=severity,
        imaging_seq_counter=imaging_seq_counter,
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
    icu_transferred_day = loop_result.get("icu_transferred_day", -1)
    differential = loop_result["differential"]
    actual_los = loop_result["actual_los"]

    # Final diagnosis
    protocol_diagnostic = protocol.diagnostic if hasattr(protocol, "diagnostic") else {}
    yaml_progression = protocol_diagnostic.get("diagnosis_progression") if protocol_diagnostic else None
    dx_code, dx_name = get_current_diagnosis_code(differential, protocol_progression=yaml_progression)

    # Diagnosis correctness and missed diagnoses (AD-29)
    missed: list[str] = []
    overcalled: list[str] = []
    if secondary_protocol and secondary_disease_id:
        # 30% chance of missing the secondary diagnosis in mixed cases
        if rng.random() < 0.30:
            missed.append(secondary_disease_id)

    # Issue #547: use the canonical registry (`icd-10-mhlw` on JP per JP Core
    # `jp-condition-diagnosis` required binding). The previous inline `"icd-10"`
    # branch emitted the WHO code system on JP inpatient encounters, whereas
    # ED / OPD paths and the FHIR emitter routed via the registry — CIF-side
    # diagnosis_system was inconsistent across encounter types.
    icd_sys = system_key_for("diagnosis", config.country)
    clinical_diagnosis = ClinicalDiagnosis(
        admission_diagnosis_code=protocol.icd_codes.get("primary", ""),
        admission_diagnosis_system=icd_sys,
        discharge_diagnosis_code=dx_code,
        discharge_diagnosis_system=icd_sys,
        # Issue #551: the engine returns ``UNRESOLVED_DIAGNOSIS_ICD`` (R69) when
        # the differential did not converge. Previous code compared against
        # ``"R05"`` (Cough) — a real ICD-10 code, which made legitimate cough
        # presentations look incorrect and disagreed with the engine's actual
        # sentinel.
        diagnosis_correct=(dx_code != UNRESOLVED_DIAGNOSIS_ICD and not missed),
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
    final_renal = state.renal_function if state else 1.0
    discharge_rx = (
        build_discharge_rx(
            patient,
            disease_id,
            protocol,
            attending_id,
            admission_time,
            encounter_id=encounter.encounter_id,
            country_key=country_key,
            final_renal_function=final_renal,
        )
        if not death_occurred
        else None
    )

    # Enrich medication orders with parsed dose/frequency/route
    from clinosim.modules.order.engine import enrich_medication_order

    for o in all_orders:
        if o.order_type == OrderType.MEDICATION:
            enrich_medication_order(o)
        # Set encounter_id for all orders that don't have one
        if not o.encounter_id:
            o.encounter_id = encounter.encounter_id

    # Set encounter discharge fields
    encounter.discharging_physician_id = attending_id
    encounter.admitting_physician_id = attending_id
    if not encounter.admit_source:
        encounter.admit_source = AdmitSource.EMD  # Most inpatients come via ED
    # CY7-05 (structural fix, 2026-07-11): populate `admit_source_encounter_id`
    # on the inpatient encounter so the FHIR adapter can emit a synthetic ED
    # Encounter with Encounter.partOf → IMP. Only sets the ID (a deterministic
    # derived string); the actual ED Encounter FHIR resource is synthesized at
    # emit time in _bb_encounters. Keeping this CIF-side change ID-only avoids
    # the record.encounters[0] contract breakage (many downstream sites assume
    # singleton) and avoids extra doc stubs for the synthesized ED.
    if encounter.admit_source == AdmitSource.EMD and not encounter.admit_source_encounter_id:
        encounter.admit_source_encounter_id = f"{encounter.encounter_id}-ED"
    if not encounter.discharge_disposition:
        if death_occurred:
            encounter.discharge_disposition = DischargeDisposition.EXP  # session 59 #299: HL7 authoritative
        else:
            encounter.discharge_disposition = DischargeDisposition.HOME
    if not encounter.priority:
        encounter.priority = ActPriority.EM if disease_id in EMERGENCY_PRIORITY_DISEASES else ActPriority.UR

    # Discharge time: daytime (09-16) for planned discharge, any time for death
    # Clinical convention: discharges happen during daytime business hours
    dc_hour = 0 if death_occurred else int(rng.normal(11, 1.5))
    dc_hour = max(9, min(16, dc_hour)) if not death_occurred else 0
    planned_discharge = _planned_discharge_datetime(admission_time, actual_los, dc_hour)

    # Snapshot truncation: if planned discharge is after snapshot date,
    # patient is still admitted as of snapshot → no discharge_datetime
    snapshot_dt = None
    if config.snapshot_date:
        snapshot_dt = datetime.strptime(config.snapshot_date, "%Y-%m-%d").replace(
            hour=23,
            minute=59,
            second=59,
        )

    if snapshot_dt and planned_discharge > snapshot_dt and not death_occurred:
        # Truncate: patient is currently admitted
        encounter.status = EncounterStatus.IN_PROGRESS
        encounter.discharge_datetime = None
        encounter.discharge_disposition = ""  # not yet discharged
        encounter.discharging_physician_id = ""
        # Drop data generated after the snapshot date
        all_orders = [o for o in all_orders if o.ordered_datetime <= snapshot_dt]
        all_vitals = [v for v in all_vitals if v.timestamp <= snapshot_dt]
        all_lab_results = [r for r in all_lab_results if r.result_datetime <= snapshot_dt]
        all_mars = [m for m in all_mars if (m.actual_datetime or m.scheduled_datetime) <= snapshot_dt]
        # Discharge prescription not yet issued
        discharge_rx = None
    else:
        encounter.status = EncounterStatus.COMPLETED
        encounter.discharge_datetime = planned_discharge
        # Issue #466: `_build_discharge_rx` runs before planned_discharge is
        # known (it consumes rng; moving it later would shift the cohort per
        # AD-16). Backfill the correct issue_date here — pure assignment, no
        # rng consumption. Also lets the FHIR adapter drop its inpatient
        # workaround (fhir_r4_adapter.py `_bb_discharge_medication_requests`).
        if discharge_rx is not None:
            discharge_rx.issue_date = planned_discharge

    # Microbiology cultures + susceptibilities (AD-55 Base) — infections only.
    # Encounter-scoped sub-seed keeps the main random stream unperturbed (AD-16).
    from clinosim.modules.observation.microbiology import generate_microbiology, has_microbiology

    microbiology: list = []
    if has_microbiology(disease_id):
        microbiology = generate_microbiology(
            disease_id,
            admission_time,
            encounter.encounter_id,
            config.random_seed,
        )
        if snapshot_dt:  # drop cultures not yet resulted as of snapshot
            microbiology = [
                m for m in microbiology if m.reported_datetime is None or m.reported_datetime <= snapshot_dt
            ]

    # RM-7d (session 42): acquired chronic conditions during inpatient stay.
    # Real EHR practice: hospitalization commonly surfaces newly-diagnosed
    # chronic disease (new-onset HTN, DM, AF, CKD, HF, IHD detected in
    # workup). We map primary disease_id → likely-implied chronic ICD codes
    # and append to patient.chronic_conditions when the code is not already
    # present. Downstream FHIR emission picks these up as problem-list-item.
    _IMPLIED_CHRONIC_BY_DISEASE = {
        "acute_mi": ["I25", "I10", "E78"],  # IHD, HTN, dyslipidemia
        "cerebral_infarction": ["I10", "I48", "I25", "E78"],
        "hemorrhagic_stroke": ["I10", "I48"],
        "subdural_hematoma": ["I10"],
        "heart_failure_exacerbation": ["I50", "I25", "I10"],
        "atrial_fibrillation_rvr": ["I48", "I50", "I10"],
        "pulmonary_embolism": ["I48", "N40"],
        "sepsis": ["N18"],
        "diabetic_ketoacidosis": ["E11.9", "E78"],
        "acute_kidney_injury": ["N18", "I10", "E11.9"],
        "hip_fracture": ["M81", "M17"],
        "urinary_tract_infection": ["N40"],
        "acute_pancreatitis": ["K74"],
        "gi_bleeding": ["K74", "K21"],
        "copd_exacerbation": ["J44"],
        "asthma_exacerbation": ["J45"],
        "bacterial_pneumonia": ["J44"],
        "aspiration_pneumonia": ["F00", "K21"],
    }
    _existing_codes = {
        (c.code.split(".")[0] if hasattr(c, "code") else str(c).split(".")[0])
        for c in (getattr(patient, "chronic_conditions", []) or [])
    }
    # Session 45 seed=400 verification finding: N40 (BPH) is anatomically
    # male-only, but the implied-chronic table was applying it sex-blind.
    # Register sex constraints per code so future additions are safe by
    # default (single edit point; sibling-sweep-safe pattern).
    _SEX_RESTRICTED_ICD = {
        "N40": "M",  # Benign prostatic hyperplasia — male only
    }
    _patient_sex = str(getattr(patient, "sex", "") or "").upper()[:1]
    _implied = _IMPLIED_CHRONIC_BY_DISEASE.get(disease_id, [])
    if _implied:
        from clinosim.types.patient import ChronicCondition

        _adm_date = getattr(admission_time, "date", lambda: admission_time)()
        for _code in _implied:
            _base = _code.split(".")[0]
            if _base in _existing_codes:
                continue
            _sex_req = _SEX_RESTRICTED_ICD.get(_base)
            if _sex_req and _patient_sex and _sex_req != _patient_sex:
                continue  # skip sex-restricted ICD for the wrong sex
            _existing_codes.add(_base)
            patient.chronic_conditions.append(
                ChronicCondition(
                    code=_code,
                    onset_date=_adm_date,
                )
            )

    # Session 45 seed=400 verification: propagate in-hospital death to the
    # Patient record so `_fhir_patient` can emit `deceasedDateTime`. Uses
    # the encounter's discharge_datetime (set to the death moment in the
    # simulator when death_occurred is True).
    if death_occurred and encounter.discharge_datetime is not None:
        _dod = (
            encounter.discharge_datetime.date()
            if hasattr(encounter.discharge_datetime, "date")
            else encounter.discharge_datetime
        )
        if not getattr(patient, "date_of_death", None):
            patient.date_of_death = _dod

    record = CIFPatientRecord(
        patient=patient,
        encounters=[encounter],
        orders=all_orders,
        vital_signs=all_vitals,
        lab_results=all_lab_results,
        condition_event=condition_event,
        clinical_diagnosis=clinical_diagnosis,
        complications_occurred=complications_occurred,
        procedures=procedures,
        rehab_sessions=rehab_sessions,
        medication_administrations=all_mars,
        intake_output_records=all_io,
        adl_assessments=all_adl,
        microbiology=microbiology,
        discharge_prescription=discharge_rx,
        icu_transferred=icu_transferred,
        icu_transferred_day=icu_transferred_day,
        deceased=death_occurred,
        death_day=actual_los if death_occurred else None,
        is_readmission=is_readmission,
        prior_encounter_id=prior_encounter_id,
        readmission_number=readmission_number,
        physiological_states=state_history,
    )

    # POST_ENCOUNTER stage (AD-55 encounter-bound Modules) — runs after
    # the daily loop produces the full clinical course. Currently:
    #   - modules/device places CVC / catheter / ventilator based on
    #     record.icu_transferred + per-day state (which is now available).
    #   - modules/hai samples CLABSI / CAUTI / VAP onsets from device
    #     line-days (CDC NHSN baseline), appends MicrobiologyResult for
    #     culture, and writes list[HAIEvent] under extensions["hai"].
    #   - modules/imaging derives ImagingStudyRecord (FHIR) from Order(IMAGING)
    #     and writes list[ImagingStudyRecord] under extensions["imaging"].
    # Per-patient sub-seed via ENRICHER_SEED_OFFSETS so the main RNG is
    # untouched (AD-16).
    from clinosim.simulator.enrichers import (
        POST_ENCOUNTER,
        EnricherContext,
        run_stage,
    )

    # Store disease_id in extensions for enrichers that need it (e.g. imaging
    # enricher for impression template selection). Modules read via:
    #   disease_id = (record.extensions or {}).get("_disease_id", "")
    # Transient IPC key for inpatient simulator → enricher communication; cleaned up at
    # end of enricher run (e.g. imaging_enricher); NOT included in FHIR output (AD-30).
    if not record.extensions:
        record.extensions = {}
    record.extensions["_disease_id"] = disease_id

    run_stage(
        POST_ENCOUNTER,
        EnricherContext(
            config=config,
            master_seed=config.random_seed,
            records=[record],
            roster=roster,  # nursing_enricher (order=94) samples primary_nurse_id from roster
        ),
    )

    # Cleanup transient IPC key _disease_id (I-6 fix, 2026-06-30). Moved here
    # from imaging_enricher so cleanup is exception-safe (fires even if enricher
    # raises mid-loop) and future POST_ENCOUNTER enrichers at order > 90 can
    # still read _disease_id during run_stage. Underscore prefix signals transient
    # IPC key; must NOT leak into FHIR output (AD-30).
    if record.extensions:
        record.extensions.pop("_disease_id", None)

    # AD-32 snapshot truncation for encounter-bound Modules. The earlier
    # filter (lines 386-390) ran BEFORE POST_ENCOUNTER, so device + HAI
    # outputs need their own snapshot pass: drop HAI events whose onset_date
    # is past the snapshot (the patient hasn't acquired it yet as of the
    # snapshot date), drop HAI cultures whose reported_datetime is past the
    # snapshot, and re-run the microbiology truncation to catch HAI-appended
    # cultures the pre-POST_ENCOUNTER filter missed.
    if snapshot_dt is not None:
        from datetime import date as _date

        snapshot_date = snapshot_dt.date()
        ext = record.extensions or {}
        ext_hai = ext.get("hai") or []
        if ext_hai:
            kept_hai = []
            for ev in ext_hai:
                onset_str = getattr(ev, "onset_date", None) or ""
                try:
                    onset = _date.fromisoformat(onset_str)
                except (TypeError, ValueError):
                    kept_hai.append(ev)
                    continue
                if onset > snapshot_date:
                    continue
                kept_hai.append(ev)
            if len(kept_hai) != len(ext_hai):
                ext["hai"] = kept_hai
        if record.microbiology:
            record.microbiology = [
                m for m in record.microbiology if m.reported_datetime is None or m.reported_datetime <= snapshot_dt
            ]

    # Phase 3a (2026-06-25): apply HAI WBC + CRP forward-delta lift to
    # existing lab_results for any encounter day on/after each HAI
    # event's onset_date. Uses the per-day state_history to compute the
    # delta from derive_lab_values' hai_inflammation_lift kwarg so the
    # original noise + circadian on the observation values is preserved.
    from clinosim.modules.hai.lab_lift import apply_hai_lab_lift

    apply_hai_lab_lift(
        record=record,
        encounter=encounter,
        state_history=state_history,
        admission_time=admission_time,
        country=config.country,
    )

    return record


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
    attending_id: str = "",
    department: str = "internal_medicine",
    severity: str = "moderate",
    encounter_id: str = "",
    imaging_seq_counter: dict[str, int] | None = None,
) -> dict:
    """Run the day-by-day simulation loop. Returns all generated data."""

    all_orders = list(admission_orders)
    # Thread imaging sequence counter from caller (initialized at day=0 in
    # simulate_inpatient_encounter). Fallback to {"I": 0} for callers that
    # don't pass it (backward-compat for direct test calls of _run_daily_loop).
    _img_seq: dict[str, int] = imaging_seq_counter if imaging_seq_counter is not None else {"I": 0}
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
    icu_transferred_day_local: int = -1  # C5-22 (session 43): day of ICU transfer

    prev_diet = ""  # last diet ordered for this patient; threaded through the day loop
    for day in range(target_los):
        # State update with diagnosis-treatment feedback
        directive = get_daily_directive(
            archetype,
            day,
            patient.physiological_profile,
            protocol_archetypes=protocol.course_archetypes or None,
            age=patient.age,
            rng=rng,
        )

        # Phase 1: Dampen recovery if diagnosis is wrong
        dx_confidence = 0.0
        working_dx = None
        if differential.top_candidate:
            dx_confidence = differential.top_candidate.probability
            working_dx = differential.top_candidate.disease_code
        dx_difficulty = (protocol.diagnostic or {}).get("diagnostic_difficulty", 0.3)
        effectiveness = compute_diagnosis_effectiveness(
            working_dx,
            disease_id,
            dx_confidence,
            day,
            diagnostic_difficulty=dx_difficulty,
        )
        directive = apply_diagnosis_modifier(
            directive,
            effectiveness,
            current_volume=state.volume_status,
            current_ph=state.ph_status,
        )

        # Phase 2: Natural recovery (small baseline healing)
        nat_directive = natural_recovery_directive(
            day,
            disease_id,
            severity,
            patient.physiological_profile,
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
                admission_time.year,
                admission_time.month,
                admission_time.day,
                lab_hour,
                lab_min,
            ) + timedelta(days=day)

            # Context-dependent lab frequency modulation
            freq_mod = healthcare.lab_frequency_multiplier
            # Severity: severe patients get more frequent labs, mild get fewer
            severity_mult = {"severe": 1.3, "moderate": 1.0, "mild": 0.6}.get(severity, 1.0)
            freq_mod *= severity_mult
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
                protocol.model_dump(),
                patient.patient_id,
                encounter_id,
                day,
                lab_time,
                freq_mod,
                rng,
                ordered_by=attending_id,
            )
            all_orders.extend(daily_orders)

            # Imaging orders for day >= 1 (day=0 handled pre-loop in
            # simulate_inpatient_encounter). Counter threads from admission
            # call so IDs are unique across the full encounter.
            daily_imaging = place_imaging_orders(
                protocol,
                encounter_id,
                patient.patient_id,
                admission_time,
                day_index=day,
                severity=severity,
                rng=rng,
                sequence_counter=_img_seq,
            )
            all_orders.extend(daily_imaging)

        # Chronic condition monitoring labs (additional to disease protocol)
        if chronic_monitoring and day >= 1:
            chronic_lab_orders = _place_chronic_monitoring_orders(
                chronic_monitoring,
                patient.patient_id,
                day,
                admission_time,
                rng,
                encounter_id=encounter_id,
                ordered_by=attending_id,
            )
            all_orders.extend(chronic_lab_orders)

        # Lab results (with temporal lag for slow markers like CRP)
        lab_hour = lab_time.hour if "lab_time" in dir() else 6  # early morning default
        # J5 (Phase 2a): read every scenario flag (causes_myocardial_injury,
        # causes_vte, future additions) via one helper and splat with **flags
        # so every call site stays in sync. See physiology.engine docstring.
        # Phase 2b (2026-06-24): sibling helper medication_flags_from_context
        # detects chronic warfarin from current_medications AND in-hospital
        # warfarin orders >= 3 days old (loading-dose 3-day rule). Both
        # helpers spread as **flags so a new flag added to derive_lab_values
        # reaches this site without touching the call.
        _med_orders = [o for o in all_orders if o.order_type.value == "medication"]
        flags = {
            **scenario_flags_from_protocol(protocol),
            **medication_flags_from_context(
                patient,
                medication_orders=_med_orders,
                admission_date=admission_time.date(),
                current_day=day,
            ),
        }
        true_labs = derive_lab_values(
            state, sex=patient.sex, age=patient.age, has_diabetes=has_diabetes, hour=lab_hour, **flags
        )  # noqa: E501

        # Apply temporal lag: CRP reflects inflammation from ~1 day ago
        if len(state_history) >= 2 and "CRP" in true_labs:
            lag_idx = max(0, len(state_history) - 2)
            lagged_state = state_history[lag_idx]
            lagged_labs = derive_lab_values(
                lagged_state, sex=patient.sex, age=patient.age, has_diabetes=has_diabetes, hour=lab_hour, **flags
            )  # noqa: E501
            true_labs["CRP"] = lagged_labs.get("CRP", true_labs["CRP"])

        # Expand panel orders (e.g. ABG → pH/pCO2/pO2/HCO3; CBC → WBC/Hb/Hct/Plt) into
        # component child lab orders. The parent is marked RESULTED (no scalar result →
        # no duplicate Observation). Children are kept *separate* from the master
        # parent stream so their RNG draws can run on a per-parent isolated sub-RNG
        # (see Pass 2 below), preventing panel-registry edits from cascading into
        # unrelated patients' cohorts (AD-16).
        _panel_children_by_parent: dict[str, list[Order]] = {}
        for order in all_orders:
            if order.order_type.value == "lab" and order.status == OrderStatus.PLACED:
                comps = lab_panel_components(order.display_name)
                if not comps:
                    continue
                children: list[Order] = []
                for comp_name in comps:
                    children.append(
                        Order(
                            order_id=f"{order.order_id}-{comp_name}",
                            patient_id=order.patient_id,
                            order_type=OrderType.LAB,
                            display_name=comp_name,
                            urgency=order.urgency,
                            clinical_intent=order.clinical_intent,
                            ordered_datetime=order.ordered_datetime,
                            ordered_by=order.ordered_by,
                            encounter_id=order.encounter_id,
                            status=OrderStatus.PLACED,
                        )
                    )
                _panel_children_by_parent[order.order_id] = children
                order.status = OrderStatus.RESULTED

        # The flat list (preserves insertion order so downstream serialisers, e.g.
        # _bb_labs in fhir_r4_adapter, retain a stable index for `lab-{enc}-{idx:04d}`).
        _panel_children: list[Order] = [c for kids in _panel_children_by_parent.values() for c in kids]
        all_orders.extend(_panel_children)
        _panel_child_ids = {c.order_id for c in _panel_children}

        # === Pass 1: scalar + non-panel orders, drawn from a per-order isolated
        # sub-RNG (individual_lab_seed). This mirrors the panel-children Pass 2
        # design: each individual lab order is one specimen, so specimen
        # rejection, hemolysis, technician assignment, and noise must come from
        # an isolated stream so YAML edits that flip a {test:"X"} order from
        # "engine doesn't produce X" to "engine produces X" (e.g. Cl/Ca after
        # derive_lab_values is extended) cannot shuffle unrelated patients'
        # cohorts via the master stream (AD-16). Panel children are skipped
        # here; they are resulted in Pass 2 against panel_specimen_seed.
        for order in all_orders:
            if order.order_id in _panel_child_ids:
                continue
            canon = canonical_lab_name(order.display_name)
            if order.order_type.value == "lab" and order.status == OrderStatus.PLACED and canon in true_labs:
                lab_rng = np.random.default_rng(individual_lab_seed(order.order_id))
                # Pre-analytical issues (constants in observation/pre_analytical.py):
                # ~2% specimen rejection, ~3% hemolysis on K/LDH.
                if lab_rng.random() < SPECIMEN_REJECTION_RATE:
                    order.status = OrderStatus.CANCELLED
                    continue  # specimen lost/rejected
                if canon in HEMOLYSIS_PRONE_LABS and lab_rng.random() < HEMOLYSIS_RATE:
                    # Hemolyzed sample → falsely elevated K/LDH, flagged
                    result_time = calculate_result_time_from_state(order, hospital_state, hospital_ops or {}, lab_rng)
                    hemolyzed_val = true_labs[canon] * float(lab_rng.uniform(*HEMOLYSIS_LIFT_RANGE))
                    lab_tech = assign_staff("lab_result", "", roster, lab_rng).get(
                        "performing_technician", FALLBACK_TECH_ID
                    )
                    order.result = OrderResult(
                        result_datetime=result_time,
                        performed_by=lab_tech,
                        lab_name=canon,
                        value=round(hemolyzed_val, 1),
                        unit=get_lab_unit(canon),
                        flag="H*",
                    )
                    order.status = OrderStatus.RESULTED
                    all_lab_results.append(order.result)
                    continue

                result_time = calculate_result_time_from_state(order, hospital_state, hospital_ops or {}, lab_rng)
                observed = generate_lab_result(canon, true_labs[canon], lab_rng)
                flag = determine_flag(
                    canon, observed, sex=patient.sex, country="JP" if country_key == "japan" else "US"
                )
                lab_tech = assign_staff("lab_result", "", roster, lab_rng).get(
                    "performing_technician", FALLBACK_TECH_ID
                )
                order.result = OrderResult(
                    result_datetime=result_time,
                    performed_by=lab_tech,
                    lab_name=canon,
                    value=observed,
                    unit=get_lab_unit(canon),
                    flag=flag,
                )
                order.status = OrderStatus.RESULTED
                all_lab_results.append(order.result)

        # === Pass 2: panel children, one isolated sub-RNG per parent specimen.
        # Clinical model: a panel order is **one specimen**, so specimen-rejection
        # fires at most once per parent and cancels every child of that parent.
        # Per-analyte hemolysis is drawn after specimen acceptance. Components not
        # present in true_labs (e.g. BMP Cl/Ca until derive_lab_values produces them)
        # are silently skipped — the child stays PLACED with no result, matching
        # the existing behaviour for any individual order that engine cannot result.
        for parent_id, children in _panel_children_by_parent.items():
            sub_rng = np.random.default_rng(panel_specimen_seed(parent_id))
            if sub_rng.random() < SPECIMEN_REJECTION_RATE:
                for child in children:
                    child.status = OrderStatus.CANCELLED
                continue
            for child in children:
                canon = canonical_lab_name(child.display_name)
                if canon not in true_labs:
                    continue  # silently dropped; status stays PLACED
                result_time = calculate_result_time_from_state(
                    child,
                    hospital_state,
                    hospital_ops or {},
                    sub_rng,
                )
                lab_tech = assign_staff(
                    "lab_result",
                    "",
                    roster,
                    sub_rng,
                ).get("performing_technician", FALLBACK_TECH_ID)
                if canon in HEMOLYSIS_PRONE_LABS and sub_rng.random() < HEMOLYSIS_RATE:
                    hemolyzed_val = true_labs[canon] * float(sub_rng.uniform(*HEMOLYSIS_LIFT_RANGE))
                    child.result = OrderResult(
                        result_datetime=result_time,
                        performed_by=lab_tech,
                        lab_name=canon,
                        value=round(hemolyzed_val, 1),
                        unit=get_lab_unit(canon),
                        flag="H*",
                    )
                else:
                    observed = generate_lab_result(canon, true_labs[canon], sub_rng)
                    flag = determine_flag(
                        canon, observed, sex=patient.sex, country="JP" if country_key == "japan" else "US"
                    )
                    child.result = OrderResult(
                        result_datetime=result_time,
                        performed_by=lab_tech,
                        lab_name=canon,
                        value=observed,
                        unit=get_lab_unit(canon),
                        flag=flag,
                    )
                child.status = OrderStatus.RESULTED
                all_lab_results.append(child.result)

        # Diagnosis update
        if day >= 1:
            findings = _extract_findings(all_lab_results, disease_id, day)
            if findings:
                protocol_lr = (
                    protocol.likelihood_ratios
                    if hasattr(protocol, "likelihood_ratios") and protocol.likelihood_ratios
                    else None
                )  # noqa: E501
                protocol_diagnostic = protocol.diagnostic if hasattr(protocol, "diagnostic") else {}
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
                all_orders.append(
                    Order(
                        order_id=f"ORD-{encounter_id}-MOD-D{day}-{sanitize_id_token(lab_name, 5)}",
                        patient_id=patient.patient_id,
                        order_type=OrderType.LAB,
                        display_name=lab_name,
                        urgency="stat",
                        clinical_intent=f"Day {day} {archetype}: additional workup",
                        ordered_datetime=admission_time + timedelta(days=day, hours=10),
                        status=OrderStatus.PLACED,
                    )
                )
            # Add imaging
            for img_idx, img_name in enumerate(mod.get("add_imaging", [])):
                all_orders.append(
                    Order(
                        order_id=f"ORD-{encounter_id}-MOD-D{day}-IMG-{img_idx}",
                        patient_id=patient.patient_id,
                        order_type=OrderType.IMAGING,
                        display_name=img_name,
                        urgency="stat",
                        clinical_intent=f"Day {day} {archetype}: additional imaging",
                        ordered_datetime=admission_time + timedelta(days=day, hours=10),
                        status=OrderStatus.PLACED,
                    )
                )

        # Treatment modifications (same jitter logic)
        matched_tx_key = None
        for dk in day_keys_to_check:
            if dk in treatment_mods:
                matched_tx_key = dk
                break

        if matched_tx_key:
            mod = treatment_mods[matched_tx_key]
            # Stop medications
            for stop_idx, drug_name in enumerate(mod.get("stop", [])):
                all_orders.append(
                    Order(
                        order_id=(
                            f"ORD-{encounter_id}{MED_STOP_ORDER_ID_MARKER}"
                            f"D{day}-{stop_idx}-{sanitize_id_token(drug_name, 8)}"
                        ),
                        patient_id=patient.patient_id,
                        order_type=OrderType.MEDICATION,
                        display_name=f"DISCONTINUE: {drug_name}",
                        urgency="routine",
                        clinical_intent=f"Day {day} {archetype}: stop {drug_name}",
                        ordered_datetime=admission_time + timedelta(days=day, hours=10),
                        status=OrderStatus.PLACED,
                    )
                )
            # Start new medications or procedures
            start_meds = mod.get("start", {}).get(country_key, mod.get("start", []))
            if isinstance(start_meds, list):
                for med in start_meds:
                    if not isinstance(med, dict):
                        continue
                    drug = med.get("drug", "").strip()
                    proc = med.get("procedure", "").strip()
                    if drug:
                        # Daily-loop step medications sometimes carry device or
                        # therapy names disguised as drugs (NIV_BiPAP / CPAP /
                        # IPC / cardiac monitoring / etc.). Classify via the
                        # canonical treatment_classifier (single source of
                        # truth; J5 pattern prevention — this was C4-28's
                        # RM-6b sibling gap in session 43).
                        display = f"{drug} {med.get('dose', '')}".strip()
                        _dc_order_type = classify_encounter_treatment(drug)
                        _is_medication = _dc_order_type == OrderType.MEDICATION
                        if _is_medication:
                            _order_id_prefix = f"ORD-{encounter_id}-START-D{day}-{sanitize_id_token(drug, 8)}"
                            _intent = f"Day {day} {archetype}: new medication"
                        else:
                            _order_id_prefix = f"ORD-{encounter_id}-DEV-D{day}-{sanitize_id_token(drug, 8)}"
                            _intent = f"Day {day} {archetype}: device / therapy"
                        all_orders.append(
                            Order(
                                order_id=_order_id_prefix,
                                patient_id=patient.patient_id,
                                order_type=_dc_order_type,
                                display_name=display,
                                urgency="urgent",
                                clinical_intent=_intent,
                                ordered_datetime=admission_time + timedelta(days=day, hours=10),
                                status=OrderStatus.PLACED,
                            )
                        )
                    elif proc:
                        # Procedure order (not a medication)
                        detail = med.get("detail", "")
                        display = f"{proc}" + (f" ({detail})" if detail else "")
                        all_orders.append(
                            Order(
                                order_id=f"ORD-{encounter_id}-PROC-D{day}-{sanitize_id_token(proc, 8)}",
                                patient_id=patient.patient_id,
                                order_type=OrderType.PROCEDURE,
                                display_name=display,
                                urgency="urgent",
                                clinical_intent=f"Day {day} {archetype}: new procedure",
                                ordered_datetime=admission_time + timedelta(days=day, hours=10),
                                status=OrderStatus.PLACED,
                            )
                        )
                    # Skip entries with neither drug nor procedure

        # Treatment escalation: if inflammation not improving by day 3, escalate
        if day == 3 and state.inflammation_level > 0.3:
            escalation_drugs = protocol.drugs.get("escalation", {}).get(country_key, [])
            if isinstance(escalation_drugs, dict):
                escalation_drugs = [escalation_drugs]
            for esc_drug in escalation_drugs:
                if not isinstance(esc_drug, dict):
                    continue
                drug_name = esc_drug.get("drug", "")
                dose = esc_drug.get("dose", "")
                indication = esc_drug.get("indication", "no improvement")
                # Escalation entries carry a `drug` field but the value is
                # sometimes actually a procedure name (Vertebroplasty,
                # Hemodialysis, endoscopy, etc.). Route via the canonical
                # treatment_classifier (J5 pattern prevention).
                _esc_display = f"{drug_name} {dose}".strip()
                _esc_order_type = classify_escalation_treatment(esc_drug)
                all_orders.append(
                    Order(
                        order_id=f"ORD-{encounter_id}-ESC-D{day}-{sanitize_id_token(drug_name, 8)}",
                        encounter_id=encounter_id,
                        patient_id=patient.patient_id,
                        order_type=_esc_order_type,
                        order_code=esc_drug.get("code_yj") or esc_drug.get("code_rxnorm") or "",
                        display_name=_esc_display,
                        urgency="urgent",
                        clinical_intent=f"Escalation day {day}: {drug_name} ({indication})",
                        ordered_datetime=admission_time + timedelta(days=day, hours=10),
                        ordered_by=attending_id,
                        status=OrderStatus.PLACED,
                        route=esc_drug.get("route", "IV"),
                        # Issue #476: propagate authored localized dose
                        # instructions from YAML so the FHIR builder can emit
                        # them as country-scoped `dosageInstruction.text`.
                        dose_text_ja=esc_drug.get("dose_ja", ""),
                        dose_text_en=esc_drug.get("dose_en", ""),
                    )
                )

        # Medication administration (MAR)
        mars_today = _generate_mar(
            patient, all_orders, day, admission_time, department=department, roster=roster, rng=rng
        )  # noqa: E501
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
        if diet != prev_diet:
            all_orders.append(
                Order(
                    order_id=f"ORD-{encounter_id}-DIET-D{day}",
                    patient_id=patient.patient_id,
                    order_type=OrderType.DIET,
                    display_name=diet,
                    urgency="routine",
                    clinical_intent=f"Day {day} diet: {diet}",
                    ordered_datetime=admission_time + timedelta(days=day, hours=7),
                    ordered_by=attending_id,
                    status=OrderStatus.PLACED,
                )
            )
            prev_diet = diet

        # Vitals
        ward_nurse_id = assign_staff("medication_administration", department, roster, rng).get(
            "administering_nurse", FALLBACK_NURSE_ID
        )  # noqa: E501
        vitals_country = "JP" if country_key == "japan" else "US"
        vitals_today = _generate_vitals(
            state,
            patient,
            day,
            admission_time,
            rng,
            disease_id=disease_id,
            nurse_id=ward_nurse_id,
            country=vitals_country,
        )  # noqa: E501
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
            triggered = evaluate_complications(
                day,
                state,
                patient,
                comp_list,
                active_complications,
                rng,
                severity=severity,
            )
            for comp in triggered:
                for var, delta in comp.get("state_impact", {}).items():
                    apply_state_delta(state, var, delta)
                comp_name = comp.get("name", "unknown")
                complications_occurred.append(comp_name)
                if "icu_transfer" in comp.get("actions", []):
                    if not icu_transferred:
                        # C5-22 (session 43): capture day of transfer for
                        # Encounter.classHistory. First trigger wins;
                        # subsequent ICU-triggering complications on later
                        # days do not overwrite (the patient is already in
                        # ICU by then).
                        icu_transferred_day_local = day
                    icu_transferred = True
                # Cancel contraindicated meds when AKI develops as complication
                if comp_name == "acute_kidney_injury":
                    for o in all_orders:
                        if o.order_type == OrderType.MEDICATION and o.status == OrderStatus.PLACED:
                            if "metformin" in (o.display_name or "").lower():
                                o.status = OrderStatus.CANCELLED

        # Mortality (disease-specific rate from YAML benchmarks)
        benchmark_mortality = protocol.outcome_benchmarks.get(country_key, {}).get("in_hospital_mortality", 0.0)
        if _evaluate_mortality(
            state,
            patient,
            severity=severity,
            day=day,
            rng=rng,
            disease_mortality_rate=benchmark_mortality,
            target_los=target_los,
        ):
            death_occurred = True
            break

        # Early discharge: if state-based criteria met before target_los
        if day >= min_los and not death_occurred:
            if _check_discharge_ready(state, day, country_key):
                break  # actual_los = day + 1

    try:
        actual_los = day + 1
    except NameError:
        actual_los = max(1, target_los)
    return {
        "orders": all_orders,
        "lab_results": all_lab_results,
        "vitals": all_vitals,
        "mars": all_mars,
        "io_records": all_io,
        "adl_assessments": all_adl,
        "state_history": state_history,
        "complications": complications_occurred,
        "death_occurred": death_occurred,
        "icu_transferred": icu_transferred,
        "icu_transferred_day": icu_transferred_day_local,  # C5-22
        "differential": differential,
        "actual_los": actual_los,
    }


# ============================================================
# Discharge prescription
# ============================================================


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
