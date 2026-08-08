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

from clinosim.modules.encounter.engine import create_inpatient_encounter
from clinosim.modules.observation.engine import (
    determine_flag,
    generate_lab_result,
    get_lab_unit,
)
from clinosim.modules.order.engine import calculate_result_time_from_state
from clinosim.modules.physiology.engine import (
    derive_lab_values,
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
from clinosim.simulator.helpers import pick_ward, resolve_department
from clinosim.types.clinical import ClinicalDiagnosis, ConditionEvent
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
    # `_generate_vitals` now lives in `vitals_pipeline` (PR B); `_generate_mar`
    # is still in `inpatient` (moves in PR C — until then imported from there
    # directly, which is fine because it's a first-class definition, not a
    # re-export).
    from clinosim.simulator.inpatient import _generate_mar
    from clinosim.simulator.vitals_pipeline import _generate_vitals

    state = initialize_state(patient.physiological_profile, patient.chronic_conditions, patient.patient_id)
    state.inflammation_level += float(rng.uniform(0.10, 0.30))

    admission_time = datetime(
        event.timestamp.year, event.timestamp.month, event.timestamp.day, int(rng.integers(8, 22)), 0
    )
    state.timestamp = admission_time
    complaint = event.disease_id.replace("unknown_", "").replace("_", " ")
    encounter = create_inpatient_encounter(patient.patient_id, admission_time, chief_complaint=complaint)
    # Unknown conditions are managed by internal medicine — resolve via hospital config
    department = resolve_department("internal_medicine", hospital_ops)
    encounter.department_id = department
    attending_id = assign_staff("admission", department, roster, rng).get("attending_physician", FALLBACK_PHYSICIAN_ID)
    encounter.attending_physician_id = attending_id
    encounter.ward_id = pick_ward(department, hospital_ops, rng)
    ward_cap = (hospital_ops or {}).get("ward_capacity", {}).get(encounter.ward_id, 10)
    bed_idx = int(rng.integers(1, ward_cap + 1))
    encounter.bed_number = f"{encounter.ward_id}-{bed_idx:02d}"

    target_los = int(rng.integers(7, 14))  # unknown conditions: longer workup
    all_vitals: list[VitalSignRecord] = []
    all_orders: list[Order] = []
    all_lab_results: list[OrderResult] = []
    state_history = [deepcopy(state)]
    has_diabetes = any(c.code.startswith("E11") for c in patient.chronic_conditions)

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
                clinical_intent=f"Unknown {complaint}: initial workup",
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
                clinical_intent=f"Unknown {complaint}: imaging workup",
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
                clinical_intent=f"Unknown {complaint}: {med['intent']}",
                ordered_datetime=admission_time + timedelta(minutes=30),
                ordered_by=attending_id,
                status=OrderStatus.PLACED,
            )
        )
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
                all_orders.append(
                    Order(
                        order_id=f"ORD-{encounter.encounter_id}-D4-IMG",
                        patient_id=patient.patient_id,
                        order_type=OrderType.IMAGING,
                        display_name="CT_chest_with_contrast",
                        urgency="routine",
                        clinical_intent="Day 4: expanded imaging for unknown fever",
                        ordered_datetime=admission_time + timedelta(days=4, hours=10),
                        ordered_by=attending_id,
                        status=OrderStatus.PLACED,
                    )
                )

            for i, lab_name in enumerate(daily_labs):
                lab_time = admission_time + timedelta(days=day, hours=6)
                all_orders.append(
                    Order(
                        order_id=f"ORD-{encounter.encounter_id}-D{day}-L{i:02d}",
                        patient_id=patient.patient_id,
                        order_type=OrderType.LAB,
                        display_name=lab_name,
                        urgency="routine",
                        clinical_intent=f"Day {day}: monitoring + workup",
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
        true_labs = derive_lab_values(
            state, sex=patient.sex, age=patient.age, has_diabetes=has_diabetes, **_flags_unknown
        )  # noqa: E501
        for order in all_orders:
            if (
                order.order_type.value == "lab"
                and order.status == OrderStatus.PLACED
                and order.display_name in true_labs
            ):  # noqa: E501
                result_time = calculate_result_time_from_state(
                    order, None, {}, rng
                )  # unknown condition: no hospital state  # noqa: E501
                observed = generate_lab_result(order.display_name, true_labs[order.display_name], rng)
                flag = determine_flag(
                    order.display_name,
                    observed,
                    sex=patient.sex,
                    country=config.country if config else "US",
                )
                tech_id = assign_staff("lab_result", "", roster, rng).get("performing_technician", FALLBACK_TECH_ID)
                order.result = OrderResult(
                    result_datetime=result_time,
                    performed_by=tech_id,
                    lab_name=order.display_name,
                    value=observed,
                    unit=get_lab_unit(order.display_name),
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
    encounter.discharge_datetime = admission_time + timedelta(days=target_los, hours=14)

    # ~50% of unknown conditions get partially resolved during stay
    # (workup finds something, but not a definitive diagnosis)
    if rng.random() < 0.5:
        discharge_code = "R50.9" if "fever" in event.disease_id else "R53.1"
        "Unresolved " + complaint
    else:
        # Partially resolved: nonspecific diagnosis assigned
        discharge_code = "R50.9" if "fever" in event.disease_id else "R68.8"
        complaint.title() + " (under investigation, outpatient follow-up)"

    # Set encounter_id for all orders that don't have one — mirrors the
    # identical loop in simulate_inpatient (line 361-363). Without this,
    # _fhir_service_request._build_sr_skeleton raises AssertionError on
    # JP cohorts where unknown-condition patients generate ADM-L orders
    # without encounter_id, causing FHIR export to fail.
    for o in all_orders:
        if not o.encounter_id:
            o.encounter_id = encounter.encounter_id

    # Note: unknown-condition encounters intentionally do NOT run the
    # POST_ENCOUNTER stage (device + hai). _simulate_unknown_condition never
    # sets record.icu_transferred = True (line 511 default), and modules/
    # device/engine.place_devices_for_encounter early-returns [] when
    # icu_transferred is False. So the enrichers + apply_hai_lab_lift would
    # uniformly no-op here; the post-PR-90 xhigh review caught a 29-line
    # dead block at this spot and it was removed. If a future requirement
    # adds ICU transfer to unknown-condition simulation, gate the hook on
    # icu_transferred just like every other AD-32-aware code path.
    return CIFPatientRecord(
        patient=patient,
        encounters=[encounter],
        orders=all_orders,
        vital_signs=all_vitals,
        lab_results=all_lab_results,
        medication_administrations=all_mars,
        condition_event=ConditionEvent(
            condition_id=f"COND-{patient.patient_id}-UNK", condition_type="unknown", symptom_pattern=event.disease_id
        ),
        clinical_diagnosis=ClinicalDiagnosis(
            admission_diagnosis_code="R50.9" if "fever" in event.disease_id else "R53.1",
            admission_diagnosis_system="icd-10-cm",
            discharge_diagnosis_code=discharge_code,
            discharge_diagnosis_system="icd-10-cm",
            diagnosis_correct=False,
        ),
        physiological_states=state_history,
    )
