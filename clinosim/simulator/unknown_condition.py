"""Unknown / idiopathic condition simulation (Issue #552 PR D).

Extracted verbatim from ``clinosim/simulator/inpatient.py`` — no logic
changes. Isolates the ~265 LOC unknown-condition simulator from the
inpatient god-object so the two follow different code paths and can be
reviewed independently.

Unlike known-disease patients, unknown-condition patients undergo
extensive diagnostic workup that progressively broadens without reaching
a conclusion. The workup + supportive-med flow is intentionally
separate from the disease-protocol-driven inpatient loop because the
inputs (no ``DiseaseProtocol``, no ``EncounterProtocol``) don't fit the
known-disease pipeline.

Callers:
* ``clinosim/simulator/engine.py::run_beta`` — for events tagged
  ``event.disease_id.startswith("unknown_")``.

Depends on ``inpatient.py`` for two shared per-day helpers:
* ``_generate_vitals`` — the daily vitals producer.
* ``_generate_mar`` — the medication-administration producer.

Extracting those two helpers into their own topic modules is scheduled
for PRs B and C of Issue #552; when they land, this module's imports
update to point at the new topic modules and the ``inpatient.py``
dependency drops.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta

import numpy as np

from clinosim import determinism
from clinosim.locale.i18n import t
from clinosim.modules.encounter.engine import create_inpatient_encounter
from clinosim.modules.observation.engine import (
    canonical_lab_name,
    determine_flag,
    generate_lab_result,
    get_lab_unit,
)
from clinosim.modules.order.engine import calculate_result_time_from_state
from clinosim.modules.physiology.engine import (
    initialize_state,
    medication_flags_from_context,
    scenario_flags_from_protocol,
)
from clinosim.modules.population.engine import LifeEvent
from clinosim.modules.staff.engine import (
    FALLBACK_NURSE_ID,
    FALLBACK_PHYSICIAN_ID,
    FALLBACK_TECH_ID,
    StaffRoster,
    assign_staff,
)
from clinosim.seeding import individual_lab_seed
from clinosim.simulator._unknown_condition_thresholds import (
    UNK_ADMISSION_HOUR_MAX_EXCLUSIVE,
    UNK_ADMISSION_HOUR_MIN,
    UNK_ADMISSION_INFLAMMATION_LIFT_MAX,
    UNK_ADMISSION_INFLAMMATION_LIFT_MIN,
    UNK_AUTOIMMUNE_WORKUP_DAY,
    UNK_DAILY_INFLAMMATION_WALK_SD,
    UNK_DAILY_LAB_HOUR,
    UNK_DISCHARGE_HOUR,
    UNK_EXPANDED_IMAGING_HOUR,
    UNK_INFECTION_TUMOR_WORKUP_DAY,
    UNK_PARTIAL_RESOLUTION_PROBABILITY,
    UNK_SUPPORTIVE_MED_PLACEMENT_MIN,
    UNK_TARGET_LOS_MAX_EXCLUSIVE,
    UNK_TARGET_LOS_MIN,
    UNK_WARD_CAPACITY_DEFAULT,
)
from clinosim.simulator.diagnosis_rules import unknown_condition_codes
from clinosim.simulator.encounter_setup import attach_orders, encounter_diagnosis
from clinosim.simulator.hospital_ops import pick_ward, resolve_department
from clinosim.simulator.lab_pipeline import patient_true_labs
from clinosim.types.clinical import ConditionEvent
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


def _simulate_unknown_condition(
    patient: PatientProfile,
    event: LifeEvent,
    rng: np.random.Generator,
    healthcare: HealthcareSystemConfig,
    roster: StaffRoster,
    hospital_ops: dict | None = None,
    config: SimulatorConfig | None = None,
) -> CIFPatientRecord | None:
    """Simulate patient with unknown/idiopathic condition.

    Unlike known-disease patients, unknown condition patients undergo extensive
    diagnostic workup that progressively broadens without reaching a conclusion.
    """
    # Local import to avoid a cycle: `inpatient.py` re-exports
    # `_simulate_unknown_condition` for backwards compat, so a module-scope
    # import from `inpatient` would form a `inpatient → unknown_condition →
    # inpatient` loop. Deferred to call time keeps this module import-clean.
    # Post-PR-B (`vitals_pipeline`) + PR-C (`medication_pipeline`), both
    # helpers live in their own topic modules and unknown_condition no longer
    # needs `inpatient.py` at all — direct imports from the topic modules.
    from clinosim.simulator.medication_pipeline import _generate_mar
    from clinosim.simulator.vitals_pipeline import _generate_vitals

    state = initialize_state(patient.physiological_profile, patient.chronic_conditions, patient.patient_id)
    state.inflammation_level += float(
        rng.uniform(UNK_ADMISSION_INFLAMMATION_LIFT_MIN, UNK_ADMISSION_INFLAMMATION_LIFT_MAX)
    )

    admission_time = datetime(
        event.timestamp.year,
        event.timestamp.month,
        event.timestamp.day,
        int(rng.integers(UNK_ADMISSION_HOUR_MIN, UNK_ADMISSION_HOUR_MAX_EXCLUSIVE)),
        0,
    )
    state.timestamp = admission_time
    # Look up the sampled pattern slug (`unknown_<pattern>`) in the
    # `unknown_condition_pattern` label catalog so both EN and JA
    # display slots on the encounter are populated. Prevents the JP
    # narrative from leaking the raw slug (e.g. "elevated inflammatory
    # markers") verbatim into `chief_complaint` prose (Phase 1d-65).
    from clinosim.locale.loader import load_narrative_labels, resolve_localized_display

    _slug = event.disease_id.replace("unknown_", "", 1)
    _entry = load_narrative_labels().get("unknown_condition_pattern", {}).get(_slug, {})
    complaint = resolve_localized_display(_entry, "en", fallback=_slug.replace("_", " "))
    complaint_ja = resolve_localized_display(_entry, "ja", fallback="")
    encounter = create_inpatient_encounter(patient.patient_id, admission_time, chief_complaint=complaint)
    if complaint_ja:
        encounter.chief_complaint_ja = complaint_ja
    # Unknown conditions are managed by internal medicine — resolve via hospital config
    department = resolve_department("internal_medicine", hospital_ops)
    encounter.department_id = department
    attending_id = assign_staff("admission", department, roster, rng).get("attending_physician", FALLBACK_PHYSICIAN_ID)
    encounter.attending_physician_id = attending_id
    encounter.ward_id = pick_ward(department, hospital_ops, rng)
    ward_cap = (hospital_ops or {}).get("ward_capacity", {}).get(encounter.ward_id, UNK_WARD_CAPACITY_DEFAULT)
    bed_idx = int(rng.integers(1, ward_cap + 1))
    encounter.bed_number = f"{encounter.ward_id}-{bed_idx:02d}"

    target_los = int(
        rng.integers(UNK_TARGET_LOS_MIN, UNK_TARGET_LOS_MAX_EXCLUSIVE)
    )  # unknown conditions: longer workup
    all_vitals: list[VitalSignRecord] = []
    all_orders: list[Order] = []
    all_lab_results: list[OrderResult] = []
    state_history = [deepcopy(state)]

    # Extensive admission workup (broader than known-disease)
    admission_labs = [
        "CRP",
        "WBC",
        "Hb",
        "Plt",
        "Creatinine",
        "Na",
        "K",
        "Glucose",
        "AST",
        "ALT",
        "ALP",
        "LDH",
        "Albumin",
        "PT_INR",
        "PCT",
    ]
    for i, lab_name in enumerate(admission_labs):
        all_orders.append(
            Order(
                order_id=f"ORD-{encounter.encounter_id}-ADM-L{i:02d}",
                patient_id=patient.patient_id,
                order_type=OrderType.LAB,
                display_name=lab_name,
                urgency="stat",
                clinical_intent=t("encounter_intent.unknown_initial_workup", "en", complaint=complaint),
                # Issue #871: JA display for JP SR reasonCode.text.
                clinical_intent_ja=t("encounter_intent.unknown_initial_workup", "ja", complaint=complaint),
                ordered_datetime=admission_time,
                ordered_by=attending_id,
                status=OrderStatus.PLACED,
            )
        )

    # Imaging: CXR + CT (broader search)
    for i, img in enumerate(["Chest_Xray", "CT_abdomen_pelvis"]):
        all_orders.append(
            Order(
                order_id=f"ORD-{encounter.encounter_id}-ADM-I{i:02d}",
                patient_id=patient.patient_id,
                order_type=OrderType.IMAGING,
                display_name=img,
                urgency="stat" if i == 0 else "urgent",
                clinical_intent=t("encounter_intent.unknown_imaging", "en", complaint=complaint),
                # Issue #871: JA display for JP SR reasonCode.text.
                clinical_intent_ja=t("encounter_intent.unknown_imaging", "ja", complaint=complaint),
                ordered_datetime=admission_time + timedelta(hours=i + 1),
                ordered_by=attending_id,
                status=OrderStatus.PLACED,
            )
        )

    # Supportive medications (even unknown conditions need basic care)
    supportive_meds = [
        {"drug": "Acetaminophen 500mg PO q6h PRN", "intent": "antipyretic for fever"},
        {"drug": "IV_fluid: NS 80mL/h", "intent": "hydration"},
    ]
    # If fever is the complaint, empiric antibiotics may be started
    if "fever" in complaint:
        supportive_meds.append({"drug": "Ceftriaxone 1g IV daily", "intent": "empiric antibiotic (pending workup)"})

    for i, med in enumerate(supportive_meds):
        all_orders.append(
            Order(
                order_id=f"ORD-{encounter.encounter_id}-ADM-M{i:02d}",
                patient_id=patient.patient_id,
                order_type=OrderType.MEDICATION,
                display_name=med["drug"],
                urgency="routine",
                clinical_intent=t(
                    "encounter_intent.unknown_treatment", "en", complaint=complaint, intent=med["intent"]
                ),
                # Issue #871: JA display for JP SR reasonCode.text. `med['intent']`
                # is the free-text EN intent from the local dict — kept as-is,
                # only the shell is translated (a follow-up PR can extend the
                # local supportive_meds dict with `intent_ja` slots).
                clinical_intent_ja=t(
                    "encounter_intent.unknown_treatment", "ja", complaint=complaint, intent=med["intent"]
                ),
                ordered_datetime=admission_time + timedelta(minutes=UNK_SUPPORTIVE_MED_PLACEMENT_MIN),
                ordered_by=attending_id,
                status=OrderStatus.PLACED,
            )
        )
    all_mars: list[MedicationAdministration] = []

    for day in range(target_los):
        # State: slow random walk (no clear trajectory)
        state.inflammation_level += float(rng.normal(0, UNK_DAILY_INFLAMMATION_WALK_SD))
        state.inflammation_level = max(0.0, min(1.0, state.inflammation_level))
        state_history.append(deepcopy(state))

        # Daily labs (more frequent than known-disease: still investigating)
        if day >= 1:
            daily_labs = ["CRP", "WBC", "Creatinine"]
            # Additional workup on specific days
            if day == UNK_INFECTION_TUMOR_WORKUP_DAY:
                daily_labs.extend(["Ferritin", "LDH", "PCT"])  # infection/tumor markers
            if day == UNK_AUTOIMMUNE_WORKUP_DAY:
                daily_labs.extend(["ANA", "RF"])  # autoimmune screening
                # Additional imaging
                all_orders.append(
                    Order(
                        order_id=f"ORD-{encounter.encounter_id}-D4-IMG",
                        patient_id=patient.patient_id,
                        order_type=OrderType.IMAGING,
                        display_name="CT_chest_with_contrast",
                        urgency="routine",
                        clinical_intent=t("encounter_intent.unknown_fever_day4_imaging", "en"),
                        # Issue #871: JA display for JP SR reasonCode.text.
                        clinical_intent_ja=t("encounter_intent.unknown_fever_day4_imaging", "ja"),
                        ordered_datetime=admission_time
                        + timedelta(days=UNK_AUTOIMMUNE_WORKUP_DAY, hours=UNK_EXPANDED_IMAGING_HOUR),
                        ordered_by=attending_id,
                        status=OrderStatus.PLACED,
                    )
                )

            for i, lab_name in enumerate(daily_labs):
                lab_time = admission_time + timedelta(days=day, hours=UNK_DAILY_LAB_HOUR)
                all_orders.append(
                    Order(
                        order_id=f"ORD-{encounter.encounter_id}-D{day}-L{i:02d}",
                        patient_id=patient.patient_id,
                        order_type=OrderType.LAB,
                        display_name=lab_name,
                        urgency="routine",
                        clinical_intent=t("encounter_intent.unknown_daily_monitoring", "en", day=day),
                        # Issue #871: JA display for JP SR reasonCode.text.
                        clinical_intent_ja=t("encounter_intent.unknown_daily_monitoring", "ja", day=day),
                        ordered_datetime=lab_time,
                        ordered_by=attending_id,
                        status=OrderStatus.PLACED,
                    )
                )

        # Generate lab results. _simulate_unknown_condition has no disease
        # protocol by definition, so scenario_flags_from_protocol(None) is
        # called explicitly (all-False) rather than relying on a
        # comment-justified omission — this way a future scenario flag added
        # to the helper reaches this call site automatically (J5-class risk).
        # Phase 2b: chronic warfarin from patient.current_medications still
        # applies (AF chronic patient hospitalized for unknown condition has
        # therapeutic INR). Pass medication_orders=None / current_day=None so
        # only the chronic detection path runs.
        _flags_unknown = {
            **scenario_flags_from_protocol(None),
            **medication_flags_from_context(patient),
        }
        true_labs = patient_true_labs(state, patient, admission_time, _flags_unknown)
        for order in all_orders:
            canon = canonical_lab_name(order.display_name)
            if order.order_type.value == "lab" and order.status == OrderStatus.PLACED and canon in true_labs:
                # AD-16: per-lab-order sub-RNG, as in the inpatient / ED / outpatient
                # paths, so result timing, noise and technician draws never touch
                # the encounter stream (Issue #2527).
                lab_rng = determinism.default_rng(individual_lab_seed(order.order_id))
                # unknown condition: no hospital state
                result_time = calculate_result_time_from_state(order, None, {}, lab_rng)
                observed = generate_lab_result(canon, true_labs[canon], lab_rng)
                flag = determine_flag(
                    canon,
                    observed,
                    sex=patient.sex,
                    country=config.country if config else "US",
                    medications=patient.current_medications,
                    age=patient.age,
                )
                tech_id = assign_staff("lab_result", "", roster, lab_rng).get("performing_technician", FALLBACK_TECH_ID)
                order.result = OrderResult(
                    result_datetime=result_time,
                    performed_by=tech_id,
                    lab_name=canon,
                    value=observed,
                    unit=get_lab_unit(canon),
                    flag=flag,
                )
                order.status = OrderStatus.RESULTED
                all_lab_results.append(order.result)

        # Vitals
        unk_nurse_id = assign_staff("medication_administration", department, roster, rng).get(
            "administering_nurse", FALLBACK_NURSE_ID
        )  # noqa: E501
        all_vitals.extend(_generate_vitals(state, patient, day, admission_time, rng, nurse_id=unk_nurse_id))

        # MAR for supportive medications
        all_mars.extend(
            _generate_mar(patient, all_orders, day, admission_time, department=department, roster=roster, rng=rng)
        )  # noqa: E501

    encounter.status = EncounterStatus.COMPLETED
    encounter.discharge_datetime = admission_time + timedelta(days=target_los, hours=UNK_DISCHARGE_HOUR)

    # The stay ends unresolved, or the workup finds something short of a
    # definitive diagnosis and a nonspecific code is assigned.
    dx_codes = unknown_condition_codes(_slug)
    if rng.random() < UNK_PARTIAL_RESOLUTION_PROBABILITY:
        discharge_code = dx_codes.unresolved
    else:
        discharge_code = dx_codes.partially_resolved

    # Set encounter_id for all orders that don't have one — mirrors the
    # identical loop in simulate_inpatient (line 361-363). Without this,
    # _fhir_service_request._build_sr_skeleton raises AssertionError on
    # JP cohorts where unknown-condition patients generate ADM-L orders
    # without encounter_id, causing FHIR export to fail.
    attach_orders(all_orders, encounter)

    record = CIFPatientRecord(
        patient=patient,
        # Issue #2995: the home medications at admission, for the admission H&P.
        home_medications_at_admission=list(patient.current_medications),
        encounters=[encounter],
        orders=all_orders,
        vital_signs=all_vitals,
        lab_results=all_lab_results,
        medication_administrations=all_mars,
        condition_event=ConditionEvent(
            condition_id=f"COND-{patient.patient_id}-UNK", condition_type="unknown", symptom_pattern=event.disease_id
        ),
        clinical_diagnosis=encounter_diagnosis(
            dx_codes.admission,
            config.country if config else "US",
            discharge_code=discharge_code,
            diagnosis_correct=False,
        ),
        physiological_states=state_history,
    )

    # POST_ENCOUNTER stage — session-98 F3 fix. The original code path
    # intentionally skipped POST_ENCOUNTER, motivated by device + hai
    # enrichers no-op'ing on unknown-condition records (icu_transferred is
    # always False here). But `document_enricher`, `nursing_enricher`,
    # `adl_enricher`, and `intake_output_enricher` DO produce content for
    # every inpatient encounter regardless of ICU status — skipping them
    # left ~3-4% of completed IMP encounters (49 US / 47 JP on p=10000
    # seed=300) with ZERO Compositions, empty nursing assessments, empty
    # ADL, empty intake/output. Documents / nursing / ADL / I/O are the
    # exact EHR-record integrity signals a downstream reader expects on
    # ANY inpatient stay — unknown-condition admissions are physically
    # real hospitalizations from the patient's viewpoint. Running the
    # stage now restores the missing per-encounter clinical documentation.
    # Device + HAI enrichers self-gate on icu_transferred, so this call
    # is byte-neutral for the enrichers that were the original rationale.
    # Guarded on ``config is not None`` so unit tests that pass config=None
    # continue to work — the enricher stage requires config.country for
    # per-country spec dispatch.
    if config is not None:
        from clinosim.simulator.enrichers import POST_ENCOUNTER, EnricherContext, run_stage

        run_stage(
            POST_ENCOUNTER,
            EnricherContext(
                config=config,
                master_seed=config.random_seed,
                records=[record],
                roster=roster,
            ),
        )

    return record
