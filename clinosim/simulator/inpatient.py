"""Inpatient simulation — patient encounter, daily loop, MAR, vitals, etc."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

import numpy as np

from clinosim.codes.hl7_encounter import ActPriority, AdmitSource
from clinosim.codes.valuesets import code_by_chronic_prefix, iter_chronic_codes
from clinosim.modules._shared import CO_DISEASE_SEVERITY
from clinosim.modules.clinical_course.engine import (
    select_archetype,
)
from clinosim.modules.diagnosis.engine import (
    discharge_code_is_admissible,
    discharge_diagnosis_code,
    initialize_differential,
)
from clinosim.modules.diagnosis.nonspecific_codes import UNRESOLVED_DIAGNOSIS_ICD
from clinosim.modules.disease.acuity import (
    EMERGENCY_PRIORITY_DISEASES,
)
from clinosim.modules.disease.localization import (
    _country_to_yaml_key,
    _disease_chief_complaint,
    _disease_chief_complaint_ja,
    _disease_to_department,
    target_los_config,
)
from clinosim.modules.disease.protocol import DiseaseProtocol, working_diagnosis_code
from clinosim.modules.disease.severity import category_from_score
from clinosim.modules.encounter.engine import create_inpatient_encounter
from clinosim.modules.order.engine import (
    drop_legacy_duplicate_imaging,
    first_line_alternative_groups,
    place_admission_orders,
    place_imaging_orders,
)
from clinosim.modules.physiology.engine import (
    apply_disease_onset,
    apply_state_delta,
    initialize_state,
)
from clinosim.modules.population.engine import LifeEvent
from clinosim.modules.procedure.engine import (
    generate_bedside_procedures,
    generate_rehab_sessions,
    simulate_surgery,
)
from clinosim.modules.staff.engine import (
    FALLBACK_PHYSICIAN_ID,
    StaffRoster,
    assign_rehab_therapist,
    assign_staff,
    select_surgical_team,
)
from clinosim.modules.triage.engine import admitted_ed_stay
from clinosim.simulator._stay_thresholds import (
    ELECTIVE_SURGERY_ADMISSION_HOUR_WEIGHTS,
    ELECTIVE_SURGERY_ADMISSION_HOURS,
    EMERGENCY_ADMISSION_HOUR_MAX_EXCLUSIVE,
    EMERGENCY_ADMISSION_SEVERITY_THRESHOLD,
    INPATIENT_WARD_CAPACITY_DEFAULT,
    PLANNED_DISCHARGE_HOUR_MAX,
    PLANNED_DISCHARGE_HOUR_MEAN,
    PLANNED_DISCHARGE_HOUR_MIN,
    PLANNED_DISCHARGE_HOUR_STD,
    READMISSION_INFLAMMATION_FLOOR,
    READMISSION_RENAL_CEILING,
    TRANSFUSION_ANEMIA_LIFT,
    TRANSFUSION_VOLUME_LIFT,
    URGENT_ADMISSION_HOUR_MAX,
    URGENT_ADMISSION_HOUR_MEAN,
    URGENT_ADMISSION_HOUR_MIN,
    URGENT_ADMISSION_HOUR_STD,
)
from clinosim.simulator.complication_dx import complication_diagnosis_entries
from clinosim.simulator.complications import complication_names
from clinosim.simulator.daily_loop import SYMPTOM_AXES, _run_daily_loop
from clinosim.simulator.delirium import delirium_code, derive_delirium, has_delirium
from clinosim.simulator.discharge_gate import discharge_disposition_for
from clinosim.simulator.discharge_rx import build_discharge_rx
from clinosim.simulator.encounter_setup import (
    align_echo_procedures_to_imaging,
    attach_orders,
    encounter_diagnosis,
    fit_procedures_in_stay,
)
from clinosim.simulator.implied_chronic import implied_chronic_codes_to_add
from clinosim.simulator.injury_coding import (
    external_cause_code,
    secondary_diagnosis_codes,
    stay_primary_code,
    surgery_for_diagnosis,
)
from clinosim.simulator.medication_pipeline import _generate_home_medication_orders
from clinosim.simulator.mixed_condition import (
    CO_DISEASE_ID_INFIX,
    co_disease_course,
    co_disease_orders,
    co_disease_recognised_late,
    co_disease_recognition_day,
)
from clinosim.simulator.sepsis_severity import sepsis_severity_code
from clinosim.types.clinical import (
    ClinicalDiagnosis,
    ConditionEvent,
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


def diagnosis_code_for_patient(protocol: Any, patient: Any, code: str) -> str:
    """Refine the protocol's primary code by the patient's chronic history
    (Issue #2132): ``icd_codes.by_chronic_prefix`` maps a chronic-code prefix
    to the code that replaces the primary one, e.g. recurrent depression
    (F33) → F33.2 instead of F32.2. Other codes pass through unchanged."""
    icd = getattr(protocol, "icd_codes", None) or {}
    if code != icd.get("primary"):
        return code
    return code_by_chronic_prefix(icd.get("by_chronic_prefix"), patient) or code


def _derive_final_diagnosis(
    *,
    differential: Any,
    protocol: DiseaseProtocol,
    secondary_protocol: DiseaseProtocol | None,
    secondary_disease_id: str | None,
    patient: PatientProfile,
    config: SimulatorConfig,
    rng: np.random.Generator,
    vitals: list[VitalSignRecord],
    mars: list[MedicationAdministration],
    lab_results: list[OrderResult],
    encounter_id: str = "",
    secondary_recognised_late: bool = False,
) -> tuple[ClinicalDiagnosis, str]:
    """Walk the differential to a final discharge diagnosis + sample
    the mixed-case missed-secondary-dx coin flip.

    A sepsis stay's severity (septic shock / severe sepsis) is taken from the
    stay's ``vitals``, ``mars`` and ``lab_results`` (Issue #3269,
    ``sepsis_severity_code``) and recorded as a secondary diagnosis code; the
    discharge diagnosis stays the systemic infection (Issue #3448).

    Returns ``(clinical_diagnosis, dx_name)``. ``dx_name`` is the
    human-readable diagnosis name (used by downstream narrative /
    discharge-prescription paths); ``clinical_diagnosis`` is the
    structured :class:`ClinicalDiagnosis` for ``CIFPatientRecord``.

    The co-disease of a mixed admission is coded as a secondary diagnosis of
    the encounter (Issue #3392). It is the missed diagnosis of the stay
    (AD-29, ``missed_diagnoses``) when it was recognised late
    (``secondary_recognised_late``: worked up and treated from hospital day
    1-3, ``mixed_condition.co_disease_recognition_day``).

    RNG consumption: one ``rng.random()`` when a secondary protocol is
    attached (the AD-29 draw of the stay's stream, kept so the stream after
    it does not move; the missed outcome follows ``secondary_recognised_late``,
    a SHA of the encounter id, which the loop needed before it ran).
    """
    protocol_diagnostic = protocol.diagnostic if hasattr(protocol, "diagnostic") else {}
    yaml_progression = protocol_diagnostic.get("diagnosis_progression") if protocol_diagnostic else None
    # Issue #947: sex-gate the differential-final picker. Passing patient.sex
    # lets `get_current_diagnosis_code` walk to the next-ranked sex-compatible
    # candidate when the top pick is anatomy-locked to the opposite sex
    # (e.g. `prostatitis`/N41.0 on a UTI female patient). Non-RNG walk.
    # Issue #3258: the discharge diagnosis is the ground-truth disease's own
    # code, never another candidate of the differential.
    disease_id = str(getattr(protocol, "disease_id", "") or "")
    dx_code, dx_name = discharge_diagnosis_code(
        differential,
        disease_id=disease_id,
        primary_code=stay_primary_code(protocol, encounter_id),
        protocol_progression=yaml_progression,
        patient_sex=patient.sex,
    )
    refined = diagnosis_code_for_patient(protocol, patient, dx_code)
    if refined != dx_code:
        from clinosim.codes import lookup

        dx_code, dx_name = refined, lookup("icd-10-cm", refined, "en")
    # Issue #3448: the walked code may refine the admitted condition, never
    # replace it with a less specific or different one.
    protocol_icd = getattr(protocol, "icd_codes", None) or {}
    admitted = stay_primary_code(protocol, encounter_id)
    if (
        dx_code != UNRESOLVED_DIAGNOSIS_ICD
        and not discharge_code_is_admissible(
            dx_code, str(protocol_icd.get("primary") or ""), protocol_icd.get("discharge_refinements")
        )
        and not discharge_code_is_admissible(dx_code, admitted, protocol_icd.get("discharge_refinements"))
    ):
        from clinosim.codes import lookup

        dx_code, dx_name = admitted, lookup("icd-10-cm", admitted, "en")
    # Issue #3269 / #3448: the stay's severity (R65.20 / R65.21) is an
    # additional code sequenced after the systemic infection, never the
    # discharge (principal) diagnosis (ICD-10-CM Official Guidelines FY2026,
    # I.C.1.d.3).
    severity_code = sepsis_severity_code(dx_code, vitals=vitals, mars=mars, lab_results=lab_results)
    severity_secondary = severity_code if severity_code != dx_code and severity_code.startswith("R65.2") else None

    # Diagnosis correctness and missed diagnoses (AD-29)
    missed: list[str] = []
    overcalled: list[str] = []
    secondary_codes = secondary_diagnosis_codes(protocol, encounter_id)
    if severity_secondary and severity_secondary not in secondary_codes:
        secondary_codes.append(severity_secondary)
    if secondary_protocol and secondary_disease_id:
        rng.random()  # the AD-29 draw's place in the stay's stream (see above)
        if secondary_recognised_late:
            missed.append(secondary_disease_id)
        # Issue #3392: the co-disease is a secondary diagnosis of the stay.
        co_code = diagnosis_code_for_patient(
            secondary_protocol, patient, stay_primary_code(secondary_protocol, encounter_id)
        )
        if (
            co_code
            and co_code not in secondary_codes
            and co_code not in (dx_code, (getattr(protocol, "icd_codes", None) or {}).get("primary"))
        ):
            secondary_codes.append(co_code)

    # Issue #547: use the canonical registry (`icd-10-mhlw` on JP per JP Core
    # `jp-condition-diagnosis` required binding). The previous inline `"icd-10"`
    # branch emitted the WHO code system on JP inpatient encounters, whereas
    # ED / OPD paths and the FHIR emitter routed via the registry — CIF-side
    # diagnosis_system was inconsistent across encounter types.
    clinical_diagnosis = encounter_diagnosis(
        diagnosis_code_for_patient(protocol, patient, stay_primary_code(protocol, encounter_id)),
        config.country,
        discharge_code=dx_code,
        external_cause_code=external_cause_code(protocol, encounter_id, config.country),
        secondary_diagnosis_codes=secondary_codes,
        # Issue #551: the engine returns ``UNRESOLVED_DIAGNOSIS_ICD`` (R69) when
        # the differential did not converge. Previous code compared against
        # ``"R05"`` (Cough) — a real ICD-10 code, which made legitimate cough
        # presentations look incorrect and disagreed with the engine's actual
        # sentinel.
        diagnosis_correct=(dx_code != UNRESOLVED_DIAGNOSIS_ICD and not missed),
        missed_diagnoses=missed,
        overcalled_diagnoses=overcalled,
    )
    return clinical_diagnosis, dx_name


"""Minimum-age gate per implied-chronic ICD (p=500 review session 89).

Mirrors ``demographics.yaml:chronic_prevalence`` lower bound so the
implied path matches the random-assignment path's clinical realism
envelope. Example: a 6-year-old with ``bacterial_pneumonia`` would
otherwise pick up J44 (COPD, adult-onset) as a chronic condition.
"""


def _attach_implied_chronic_conditions(
    *,
    disease_id: str,
    patient: PatientProfile,
    admission_time: datetime,
) -> None:
    """RM-7d: append newly-diagnosed chronic conditions implied by
    the primary admission disease.

    Mutates ``patient.chronic_conditions`` in place, skipping codes
    already present, sex-locked ICDs on the wrong sex (via
    ``is_sex_locked_for``), and age-restricted ICDs on younger
    patients (via ``implied_chronic_min_age``). The onset date is
    backdated 1-14 years from a ``(patient_id, code)`` SHA hash so
    it precedes the acute admission while remaining RNG-neutral.

    Extracted from ``_simulate_patient`` per META #1633 P6.
    """
    from clinosim.modules.patient.activator import derive_implied_chronic_onset
    from clinosim.types.patient import ChronicCondition

    existing_codes = {
        (c.code.split(".")[0] if hasattr(c, "code") else str(c).split(".")[0])
        for c in (getattr(patient, "chronic_conditions", []) or [])
    }
    patient_age = int(getattr(patient, "age", 0) or 0)
    adm_date = getattr(admission_time, "date", lambda: admission_time)()
    dob = getattr(patient, "date_of_birth", None)
    for code in implied_chronic_codes_to_add(
        disease_id,
        patient_id=patient.patient_id,
        sex=str(getattr(patient, "sex", "") or ""),
        age=patient_age,
        have_bases=existing_codes,
    ):
        # Issue #1339: backdate the implied-chronic onset from
        # (patient_id, code) hash so it precedes the acute admission
        # by 1-14 years, matching the population-time sampling window.
        # RNG-neutral (deterministic per patient×code, no master-RNG
        # consumption) — see `derive_implied_chronic_onset`.
        # Issue #3037: a condition the person already has an onset for (an
        # earlier stay implied it) keeps that onset.
        backdated = patient.chronic_onset.setdefault(
            code, derive_implied_chronic_onset(patient.patient_id, code, adm_date, dob)
        )
        patient.chronic_conditions.append(
            ChronicCondition(
                code=code,
                onset_date=backdated,
            )
        )


def _derive_microbiology(
    *,
    disease_id: str,
    admission_time: datetime,
    encounter: Any,
    config: SimulatorConfig,
    snapshot_dt: datetime | None,
    orders: list[Order],
) -> list:
    """The encounter's culture results, one per culture draw (Issue #2640).

    Every culture order of the stay (protocol workup, repeat or escalation)
    is a draw and gets a result. A culture the disease's admission workup
    calls for (``microbiology.yaml`` ``cultures``) that no protocol order
    placed near admission is ordered at admission (appended to ``orders``).
    Seeded off the config master seed per draw, so the main simulation RNG
    stream is not consumed (AD-16).
    """
    from clinosim.locale.i18n import t
    from clinosim.locale.loader import order_test_display
    from clinosim.modules.observation.microbiology import (
        culture_draws,
        culture_results,
        workup_culture_order,
        workup_culture_specimens,
        workup_culture_window_hours,
    )

    enc_id = encounter.encounter_id
    draws = culture_draws(orders, enc_id)
    window = timedelta(hours=workup_culture_window_hours())
    for spec in workup_culture_specimens(disease_id, enc_id, config.random_seed):
        if any(s == spec and abs(when - admission_time) <= window for s, when in draws):
            continue
        name = workup_culture_order(spec)
        if not name:
            continue
        orders.append(
            Order(
                order_id=f"ORD-{enc_id}-ADM-MB-{spec}",
                encounter_id=enc_id,
                patient_id=encounter.patient_id,
                order_type=OrderType.LAB,
                display_name=name,
                urgency="stat",
                clinical_intent=t("encounter_intent.admission_workup", "en", test=name),
                clinical_intent_ja=t("encounter_intent.admission_workup", "ja", test=order_test_display(name, "ja")),
                ordered_datetime=admission_time,
                ordered_by=encounter.attending_physician_id,
                status=OrderStatus.PLACED,
            )
        )
        draws.append((spec, admission_time))
    draws.sort(key=lambda d: (d[1], d[0]))
    microbiology = culture_results(disease_id, list(draws), enc_id, config.random_seed)
    if snapshot_dt:
        # drop cultures not yet resulted as of snapshot
        microbiology = [m for m in microbiology if m.reported_datetime is None or m.reported_datetime <= snapshot_dt]
    return microbiology


def _admission_route_fields(protocol: Any, disease_id: str) -> tuple[AdmitSource, ActPriority]:
    """Admit source and priority for an inpatient stay of ``disease_id``.

    Elective (scheduled) admissions come from the outpatient clinic with
    priority EL; everything else is admitted through the ED (EM for
    emergency-priority diseases, UR otherwise).
    """
    if getattr(protocol, "admission_route", "emergency") == "elective":
        return AdmitSource.OUTP, ActPriority.EL
    return AdmitSource.EMD, ActPriority.EM if disease_id in EMERGENCY_PRIORITY_DISEASES else ActPriority.UR


def _finalize_discharge(
    *,
    patient: PatientProfile,
    disease_id: str,
    protocol: DiseaseProtocol,
    attending_id: str,
    admission_time: datetime,
    encounter: Any,
    country_key: str,
    state: Any,
    all_orders: list,
    death_occurred: bool,
    final_state: Any = None,
    symptom_floor: dict[str, float] | None = None,
    on_vasoactive_support: bool = False,
    aki_at_discharge: bool = False,
    fever_at_discharge: bool = False,
    lactate_high_at_discharge: bool = False,
    discharge_time: datetime | None = None,
) -> Any:
    """Build the discharge prescription + populate discharge-related
    ``encounter`` fields (physicians, admit source, disposition,
    priority) and enrich medication orders with the parsed
    dose/frequency/route surface.

    Returns the ``discharge_rx`` ``PrescriptionRecord`` (or ``None``
    when the patient died in hospital — death cases do not emit a
    discharge Rx).

    Side-effects: mutates every ``MEDICATION`` order in
    ``all_orders`` (dose / frequency / route enrichment +
    ``encounter_id`` back-fill) and the ``encounter`` resource
    (discharging_physician_id, admitting_physician_id, admit_source,
    admit_source_encounter_id, discharge_disposition, priority).

    No RNG consumption — the discharge Rx builder uses its own
    deterministic plumbing, order enrichment is a pure parse, and
    the encounter field assignments are state-reads only.

    Extracted from ``_simulate_patient`` per META #1633 P6
    (``docs/history/plans-archive/p6-god-function-split-plan.md``).
    """
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
            aki_active=aki_at_discharge,
            lactate_high=lactate_high_at_discharge,
            discharge_time=discharge_time,
            # Issue #2992: a discharge hold names only a drug the patient took.
            ordered_drugs=[o.display_name for o in all_orders if o.order_type == OrderType.MEDICATION],
            severity=str(getattr(encounter, "severity", "") or ""),
        )
        if not death_occurred
        else None
    )

    # Enrich medication orders with parsed dose/frequency/route
    from clinosim.modules.order.engine import enrich_medication_order

    for o in all_orders:
        if o.order_type == OrderType.MEDICATION:
            enrich_medication_order(o)
    attach_orders(all_orders, encounter)

    # Set encounter discharge fields
    encounter.discharging_physician_id = attending_id
    encounter.admitting_physician_id = attending_id
    route_source, route_priority = _admission_route_fields(protocol, disease_id)
    if not encounter.admit_source:
        encounter.admit_source = route_source
    # CY7-05 (structural fix, 2026-07-11): populate `admit_source_encounter_id`
    # on the inpatient encounter so the FHIR adapter can emit a synthetic ED
    # Encounter with Encounter.partOf → IMP. Only sets the ID (a deterministic
    # derived string); the actual ED Encounter FHIR resource is synthesized at
    # emit time in _bb_encounters. Keeping this CIF-side change ID-only avoids
    # the record.encounters[0] contract breakage (many downstream sites assume
    # singleton) and avoids extra doc stubs for the synthesized ED.
    if encounter.admit_source == AdmitSource.EMD and not encounter.admit_source_encounter_id:
        encounter.admit_source_encounter_id = f"{encounter.encounter_id}-ED"
    if encounter.last_known_well is None:
        # Issue #3558: an acute stroke admission records when the patient was
        # last known well (arrival minus the onset-to-arrival interval; the ED
        # phase of a via-ED admission precedes the admission by the ED stay).
        from clinosim.modules.triage.engine import admitted_ed_stay
        from clinosim.simulator.stroke_onset import last_known_well

        arrival = admission_time - admitted_ed_stay() if encounter.admit_source == AdmitSource.EMD else admission_time
        encounter.last_known_well = last_known_well(encounter.encounter_id, disease_id, arrival, country_key)
    if not encounter.discharge_disposition:
        # EXP on death (#299), SNF when still unsafe for home at the end of
        # the stay (Issue #2084), otherwise HOME.
        encounter.discharge_disposition = discharge_disposition_for(
            final_state if final_state is not None else state,
            symptom_floor,
            death_occurred,
            on_vasoactive_support=on_vasoactive_support,
            findings_unresolved=fever_at_discharge,
        )
    if not encounter.priority:
        encounter.priority = route_priority

    return discharge_rx


def _run_post_encounter_stage(
    *,
    record: CIFPatientRecord,
    config: SimulatorConfig,
    roster: StaffRoster,
    disease_id: str,
    snapshot_dt: Any,
    encounter: Any,
    state_history: list,
    admission_time: datetime,
) -> None:
    """POST_ENCOUNTER stage (AD-55 encounter-bound Modules) — runs
    after the daily loop produces the full clinical course.

    Mutates ``record`` in place:
      - modules/device places CVC / catheter / ventilator based on
        ``record.icu_transferred`` + per-day state.
      - modules/hai samples CLABSI / CAUTI / VAP onsets from device
        line-days (CDC NHSN baseline), appends MicrobiologyResult
        for culture, and writes ``list[HAIEvent]`` under
        ``extensions["hai"]``.
      - modules/imaging derives ``ImagingStudyRecord`` (FHIR) from
        ``Order(IMAGING)`` and writes ``list[ImagingStudyRecord]``
        under ``extensions["imaging"]``.

    Per-patient sub-seed via ``ENRICHER_SEED_OFFSETS`` so the main
    RNG is untouched (AD-16).

    Extracted from ``_simulate_patient`` as part of META #1633 P6
    (first-pass split; the admit / tick / discharge phases per
    ``docs/history/plans-archive/p6-god-function-split-plan.md`` remain as
    follow-up work).
    """
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
    # filter ran BEFORE POST_ENCOUNTER, so device + HAI outputs need their
    # own snapshot pass: drop HAI events whose onset_date is past the
    # snapshot (the patient hasn't acquired it yet as of the snapshot date),
    # drop HAI cultures whose reported_datetime is past the snapshot, and
    # re-run the microbiology truncation to catch HAI-appended cultures the
    # pre-POST_ENCOUNTER filter missed.
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
    population_death_date: date | None = None,
) -> CIFPatientRecord:
    """Simulate one patient's complete hospital encounter.

    ``population_death_date`` is the person's death date from the population
    (Issue #3633): a stay that runs up to it ends as an in-hospital death on
    that date, so no survivor stay holds a death inside it.

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
    # Chronic symptom baselines (e.g. COPD hypoxemia, osteoarthritis pain) that
    # in-hospital recovery must not erase (Issue #2061).
    symptom_floor = {axis: getattr(state, axis) for axis in SYMPTOM_AXES if getattr(state, axis)}

    # Readmission: carry over residual state from prior hospitalization
    if is_readmission:
        # Readmitted patients have worse baseline (incomplete recovery from prior stay)
        state.inflammation_level = max(state.inflammation_level, READMISSION_INFLAMMATION_FLOOR)
        state.renal_function = min(state.renal_function, READMISSION_RENAL_CEILING)

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
            state,
            CO_DISEASE_SEVERITY,
            secondary_protocol.initial_state_impact,
            acid_base_type=secondary_protocol.acid_base_type,
        )

    # Create encounter — realistic admission time pattern
    if protocol.encounter_type == "surgical":
        # Elective surgery: morning admission
        adm_hour = int(rng.choice(ELECTIVE_SURGERY_ADMISSION_HOURS, p=ELECTIVE_SURGERY_ADMISSION_HOUR_WEIGHTS))
    elif event.severity > EMERGENCY_ADMISSION_SEVERITY_THRESHOLD:
        # Emergency: any hour, peak in evening (ED presentation)
        adm_hour = int(rng.choice(EMERGENCY_ADMISSION_HOUR_MAX_EXCLUSIVE))
    else:
        # Urgent: daytime bias
        adm_hour = int(rng.normal(URGENT_ADMISSION_HOUR_MEAN, URGENT_ADMISSION_HOUR_STD))
        adm_hour = max(URGENT_ADMISSION_HOUR_MIN, min(URGENT_ADMISSION_HOUR_MAX, adm_hour))
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
    from clinosim.simulator.hospital_ops import pick_ward, resolve_department

    granular_dept = _disease_to_department(protocol)
    department = resolve_department(granular_dept, hospital_ops)
    encounter.department_id = department
    staff = assign_staff("admission", department, roster, rng)
    attending_id = staff.get("attending_physician", FALLBACK_PHYSICIAN_ID)
    encounter.attending_physician_id = attending_id

    # Ward assignment from hospital config
    encounter.ward_id = pick_ward(department, hospital_ops, rng)
    # Bed number from hospital ward_capacity (valid range for this ward)
    ward_cap = (hospital_ops or {}).get("ward_capacity", {}).get(encounter.ward_id, INPATIENT_WARD_CAPACITY_DEFAULT)
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
    from clinosim.simulator.medication_pipeline import child_dosing

    _child = child_dosing(patient, encounter.encounter_id, admission_time, country_key)
    # Issue #3434: a patient admitted through the ED has the work-up ordered
    # in the ED, [admission - admitted_ed_stay(), admission].
    ed_period = (
        (admission_time - admitted_ed_stay(), admission_time)
        if _admission_route_fields(protocol, disease_id)[0] == AdmitSource.EMD
        else None
    )
    admission_orders = place_admission_orders(
        protocol.model_dump(),
        patient.patient_id,
        encounter.encounter_id,
        admission_time,
        country=country_key,
        rng=rng,
        ordered_by=attending_id,
        # Issue #1306: thread patient age so the pediatric DVT-prophylaxis
        # gate applies to the disease-YAML supportive-orders fallback path
        # (mirrors the enricher-side gate that already covers the
        # prophylaxis-engine emit).
        patient_age=int(getattr(patient, "age", 0) or 0),
        # Issue #2611: weight-based fluid boluses (30 mL/kg) — for a minor per
        # kg of the weight charted at admission (Issue #3004).
        patient_weight_kg=_child.weight_kg if _child else float(getattr(patient, "weight_kg", 0) or 0) or None,
        ed_period=ed_period,
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
        ed_period=ed_period,
    )
    # Issue #3394: the structured study replaces the legacy order of the same
    # body part (placed above, so the stay's RNG stream is unchanged).
    admission_orders = drop_legacy_duplicate_imaging(admission_orders, adm_imaging)
    admission_orders.extend(adm_imaging)

    # Issue #3392: the co-disease of a mixed admission is worked up and
    # treated by its own protocol's admission orders, from the admission or,
    # when it is recognised late, from hospital day 1-3. Placed with their own
    # RNG, so the primary disease's orders and the stay's stream do not move.
    co_course = None
    co_alternative_groups: tuple[tuple[str, ...], ...] = ()
    if secondary_protocol is not None:
        co_day = co_disease_recognition_day(encounter.encounter_id)
        co_orders = co_disease_orders(
            secondary_protocol,
            admission_orders,
            patient_id=patient.patient_id,
            encounter_id=encounter.encounter_id,
            admission_time=admission_time,
            treat_day=co_day,
            country_key=country_key,
            ordered_by=attending_id,
            patient_age=int(getattr(patient, "age", 0) or 0),
            patient_weight_kg=_child.weight_kg if _child else float(getattr(patient, "weight_kg", 0) or 0) or None,
            imaging_seq=imaging_seq_counter,
        )
        co_course = co_disease_course(secondary_protocol, co_day, co_orders if co_day > 0 else [])
        if co_day == 0:
            admission_orders.extend(co_orders)
            co_alternative_groups = first_line_alternative_groups(
                secondary_protocol, encounter.encounter_id, country_key, id_infix=CO_DISEASE_ID_INFIX
            )

    # Home medication orders (chronic condition continuation)
    # Issue #2995: the home medications at admission, kept on the record for
    # the admission H&P (later encounters replace patient.current_medications).
    home_medications_at_admission = list(patient.current_medications)
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

    # Issue #1066: run admission_orders through the drug_safety CPOE-style
    # gate. Contraindicated / major DDI candidates are dropped (with
    # alternative substituted where the disease YAML alternative_* block
    # or modules/drug_safety/reference_data/drug_substitution.yaml supplies one). Moderate DDI
    # candidates are kept with a caution note attached. Home meds and
    # already-accepted acute drugs form the active-med set. See
    # docs/superpowers/specs/2026-09-03-drug-safety-module-design.md.
    from clinosim.simulator.medication_pipeline import (
        apply_drug_safety_gate_to_admission_orders,
    )

    admission_orders = apply_drug_safety_gate_to_admission_orders(
        admission_orders,
        patient,
        encounter.encounter_id,
        admission_time,
        attending_id,
        protocol=protocol,
        country=country_key,
        # Issue #3274: first-line alternatives give one agent.
        alternative_groups=(
            *first_line_alternative_groups(protocol, encounter.encounter_id, country_key),
            *co_alternative_groups,
        ),
    )

    # Tracking
    procedures, rehab_sessions = [], []
    icu_transferred, death_occurred = False, False

    # Surgery (protocol-driven: requires_surgery flag in YAML)
    surgery_pain: tuple[int, float] | None = None  # Issue #2080: (operative day, pain level)
    # Issue #3258: the operation follows the stay's injury diagnosis.
    operate, surgery_overrides = surgery_for_diagnosis(
        protocol, stay_primary_code(protocol, encounter.encounter_id), severity
    )
    if operate:
        # Surgeon from the owning surgical department, anesthesiologist from
        # anesthesiology (Issue #2068)
        surgeon_id, anes_id = select_surgical_team(roster, department, rng)
        surgeon_id = surgeon_id or attending_id
        anes_id = anes_id or attending_id
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
            overrides=surgery_overrides,
        )
        procedures.append(proc)
        for var, delta in impacts.items():
            apply_state_delta(state, var, delta)
        _postop_pain = (protocol.procedure or {}).get("postoperative_pain_level")
        if _postop_pain is not None:
            surgery_pain = ((proc.start_datetime.date() - admission_time.date()).days, float(_postop_pain))
        rehab_sessions = generate_rehab_sessions(
            patient.patient_id,
            encounter.encounter_id,
            proc.start_datetime,
            target_los,
            rng,
            config.country,
            therapist_id=assign_rehab_therapist(roster, "PT", encounter.encounter_id),
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
        performer_id=encounter.attending_physician_id,
    )
    procedures.extend(bedside)

    # Apply state impacts from bedside procedures (e.g., blood transfusion)
    for proc in bedside:
        if proc.procedure_type == "blood_transfusion":
            state.anemia_level = max(0.0, state.anemia_level - TRANSFUSION_ANEMIA_LIFT)
            state.volume_status = min(1.0, state.volume_status + TRANSFUSION_VOLUME_LIFT)

    # Differential diagnosis
    protocol_diagnostic = protocol.diagnostic if hasattr(protocol, "diagnostic") else {}
    differential = initialize_differential(disease_id, patient.age, protocol_diagnostic=protocol_diagnostic)

    # Issue #3277: the chronic conditions the disease implies (atrial
    # fibrillation for a share of stroke patients) are on the patient's list
    # before the stay's orders, so the antithrombotic plan, the discharge
    # prescription, the problem list and the narratives read one list.
    _attach_implied_chronic_conditions(
        disease_id=disease_id,
        patient=patient,
        admission_time=admission_time,
    )

    # Daily simulation loop
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
        ed_start=ed_period[0] if ed_period else None,
        symptom_floor=symptom_floor,
        max_los=int(los_cfg.get("max", target_los)),
        surgery=surgery_pain,
        prior_procedures=procedures,
        co_disease=co_course,
        population_death_date=population_death_date,
    )

    # Unpack results
    all_orders = loop_result.orders
    all_lab_results = loop_result.lab_results
    all_vitals = loop_result.vitals
    all_mars = loop_result.mars
    all_io = loop_result.io_records
    all_adl = loop_result.adl_assessments
    state_history = loop_result.state_history
    complications_occurred = loop_result.complications
    # Issue #3519: a susceptible patient whose level of consciousness stays
    # reduced for days has a delirium episode (onset, duration, resolution),
    # derived from the recorded AVPU without any draw.
    _delirium = derive_delirium(
        loop_result.vitals,
        patient.physiological_profile.delirium_susceptibility,
        admission_time,
        existing=complication_names(complications_occurred),
    )
    if _delirium is not None:
        complications_occurred = [*complications_occurred, _delirium]
    death_occurred = loop_result.death_occurred
    icu_transferred = loop_result.icu_transferred
    # Issue #2091: intubation performed when the state crossed the airway threshold.
    procedures.extend(loop_result.escalation_procedures)
    icu_transferred_day = loop_result.icu_transferred_day
    differential = loop_result.differential
    actual_los = loop_result.actual_los

    clinical_diagnosis, dx_name = _derive_final_diagnosis(
        differential=differential,
        protocol=protocol,
        secondary_protocol=secondary_protocol,
        secondary_disease_id=secondary_disease_id,
        patient=patient,
        config=config,
        rng=rng,
        vitals=loop_result.vitals,
        mars=loop_result.mars,
        lab_results=loop_result.lab_results,
        encounter_id=encounter.encounter_id,
        secondary_recognised_late=co_disease_recognised_late(encounter.encounter_id),
    )

    # Issue #3673: every coded complication (acute kidney injury, deep vein
    # thrombosis, delirium, ...) is a dated working diagnosis of the stay, with
    # the onset of the complication, unless the stay already carries the code.
    _carried = [
        clinical_diagnosis.admission_diagnosis_code,
        clinical_diagnosis.discharge_diagnosis_code,
        *clinical_diagnosis.secondary_diagnosis_codes,
        *(working_diagnosis_code(str(wd.get("disease_id") or "")) for wd in clinical_diagnosis.working_diagnoses),
        *iter_chronic_codes(patient.chronic_conditions),
    ]
    clinical_diagnosis.working_diagnoses.extend(complication_diagnosis_entries(complications_occurred, _carried))

    # Issue #3519: a delirium of the stay (derived, or an ICU / postoperative
    # delirium complication) is a coded secondary diagnosis.
    _dx_primary = (clinical_diagnosis.admission_diagnosis_code, clinical_diagnosis.discharge_diagnosis_code)
    if has_delirium(complication_names(complications_occurred)) and delirium_code() not in (
        *clinical_diagnosis.secondary_diagnosis_codes,
        *_dx_primary,
    ):
        clinical_diagnosis.secondary_diagnosis_codes.append(delirium_code())

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

    # Discharge time: daytime (09-16) for planned discharge, any time for death
    # Clinical convention: discharges happen during daytime business hours
    # (Issue #3441: drawn before the discharge Rx, which stamps its holds with
    # it; _finalize_discharge draws nothing from ``rng``, so the order is neutral)
    dc_hour = 0 if death_occurred else int(rng.normal(PLANNED_DISCHARGE_HOUR_MEAN, PLANNED_DISCHARGE_HOUR_STD))
    dc_hour = max(PLANNED_DISCHARGE_HOUR_MIN, min(PLANNED_DISCHARGE_HOUR_MAX, dc_hour)) if not death_occurred else 0
    planned_discharge = _planned_discharge_datetime(admission_time, actual_los, dc_hour)

    discharge_rx = _finalize_discharge(
        patient=patient,
        disease_id=disease_id,
        protocol=protocol,
        attending_id=attending_id,
        admission_time=admission_time,
        encounter=encounter,
        country_key=country_key,
        state=state,
        all_orders=all_orders,
        death_occurred=death_occurred,
        final_state=state_history[-1] if state_history else None,
        symptom_floor=symptom_floor,
        on_vasoactive_support=loop_result.on_vasoactive_support,
        aki_at_discharge=loop_result.aki_at_discharge,
        fever_at_discharge=loop_result.fever_at_discharge,
        lactate_high_at_discharge=loop_result.lactate_high_at_discharge,
        discharge_time=planned_discharge,
    )

    # Issue #3043: a one-time order placed on the last stay day but dated the
    # next calendar day is still given before discharge.
    from clinosim.simulator.medication_pipeline import missed_single_doses

    all_mars = all_mars + missed_single_doses(
        patient,
        all_orders,
        all_mars,
        admission_time,
        planned_discharge,
        roster=roster,
        ward=encounter.ward_id or "",
        department=department,
    )

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
        # Issue #466: `build_discharge_rx` runs before planned_discharge is
        # known (it consumes rng; moving it later would shift the cohort per
        # AD-16). Backfill the correct issue_date here — pure assignment, no
        # rng consumption. Also lets the FHIR adapter drop its inpatient
        # workaround (fhir_r4_adapter.py `_bb_discharge_medication_requests`).
        if discharge_rx is not None:
            discharge_rx.issue_date = planned_discharge

    # Issue #2863: procedures lie between admission and discharge (or death).
    fit_procedures_in_stay(procedures, encounter.admission_datetime, encounter.discharge_datetime)
    # Issue #3451: an echo is one study — its procedure takes the imaging study's
    # time, which for a via-ED admission is the ED work-up time (Issue #3434).
    align_echo_procedures_to_imaging(procedures, all_orders)

    microbiology = _derive_microbiology(
        disease_id=disease_id,
        admission_time=admission_time,
        encounter=encounter,
        config=config,
        snapshot_dt=snapshot_dt,
        orders=all_orders,
    )

    # seed=400 verification: propagate in-hospital death to the
    # Patient record so `_fhir_patient` can emit `deceasedDateTime`. Uses
    # the encounter's discharge_datetime (set to the death moment in the
    # simulator when death_occurred is True).
    if death_occurred and encounter.discharge_datetime is not None:
        _dod = (
            encounter.discharge_datetime.date()
            if hasattr(encounter.discharge_datetime, "date")
            else encounter.discharge_datetime
        )
        if patient.date_of_death is None or _dod < patient.date_of_death:
            patient.date_of_death = _dod
            # Issue #2984: keep the time of death for Patient.deceasedDateTime.
            patient.death_datetime = (
                encounter.discharge_datetime if isinstance(encounter.discharge_datetime, datetime) else None
            )

    record = CIFPatientRecord(
        patient=patient,
        home_medications_at_admission=home_medications_at_admission,
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
        airway_declined=loop_result.airway_declined,
        icu_transferred_day=icu_transferred_day,
        icu_discharge_day=loop_result.icu_discharge_day,
        deceased=death_occurred,
        death_day=actual_los if death_occurred else None,
        is_readmission=is_readmission,
        prior_encounter_id=prior_encounter_id,
        readmission_number=readmission_number,
        physiological_states=state_history,
    )

    _run_post_encounter_stage(
        record=record,
        config=config,
        roster=roster,
        disease_id=disease_id,
        snapshot_dt=snapshot_dt,
        encounter=encounter,
        state_history=state_history,
        admission_time=admission_time,
    )
    return record


# ============================================================
# Daily simulation loop
# ============================================================
