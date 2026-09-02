"""Perinatal delivery encounter emission (Issue #957 Tier-3-B; the
scheduling side was extended to a full lifecycle in META #957 Incr 1).

Mother-side delivery + newborn Patient chain for a pregnant woman whose
active pregnancy period's planned_delivery_date falls in the current
sim year. Slice-2 scope:
  * Mother's inpatient delivery encounter (admission dx O80, discharge
    dx Z37.0 single liveborn, delivery Procedure).
  * Newborn Patient resource (birthDate = delivery date, sex sampled
    per-patient sub-RNG, household inherited from mother).
  * Newborn inpatient Encounter with ``admitSource = born`` and
    ``partOf`` pointing at the mother's delivery encounter (FHIR-
    standard mother→baby link).
  * Newborn Z38.0 (single liveborn, born in hospital, delivered
    without mention of caesarean section) discharge diagnosis.

Prenatal visits (weeks 12 / 24 / 36) + postpartum visits × 2
(7 d / 28 d post-delivery) are scheduled by the pregnancy-lifecycle
generator (``_pregnancy_lifecycle_events`` in ``population/engine.py``)
and dispatch through the standard chronic-followup path, routed to
obgyn via ``_CHRONIC_DISEASE_SPECIALTY``.
"""

from __future__ import annotations

import hashlib
from datetime import date, datetime, timedelta

import numpy as np

from clinosim.codes import system_key_for
from clinosim.codes.hl7_encounter import ActPriority, AdmitSource, DischargeDisposition
from clinosim.locale.loader import load_perinatal_config
from clinosim.modules._shared import is_jp
from clinosim.modules.encounter.engine import create_inpatient_encounter
from clinosim.modules.staff.engine import FALLBACK_PHYSICIAN_ID, StaffRoster, assign_staff
from clinosim.simulator.hospital_ops import resolve_department
from clinosim.types.clinical import ClinicalDiagnosis, ConditionEvent
from clinosim.types.encounter import EncounterStatus, EncounterType
from clinosim.types.output import CIFPatientRecord
from clinosim.types.patient import ChronicCondition, PatientProfile


def _newborn_sub_seed(mother_id: str) -> int:
    """Per-mother deterministic sub-seed for newborn attribute sampling
    (sex, minor details). Isolated so mother→baby linkage is stable
    across runs and independent of the calendar's master RNG."""
    salt = "clinosim:newborn:v1"
    digest = hashlib.sha256(f"{salt}|{mother_id}".encode()).digest()[:6]
    return int.from_bytes(digest, "big") % (2**32)


def _abortion_outcome_sub_seed(mother_id: str, year: int) -> int:
    """Per-(mother, year) sub-seed for the pregnancy-outcome roll (delivery
    vs abortion, and if abortion then spontaneous vs induced). Isolated
    from the newborn-attribute seeds so tuning abortion rates does not
    shift a delivered baby's sex or condition draws."""
    salt = "clinosim:pregnancy-outcome:v1"
    digest = hashlib.sha256(f"{salt}|{mother_id}|{year}".encode()).digest()[:6]
    return int.from_bytes(digest, "big") % (2**32)


def _lookup_age_band(table: dict, age: int) -> float:
    """Look up the entry in a ``"lo-hi": value`` age-band dict, returning
    the first matching value (0.0 if none matches). Same convention as
    ``chronic_prevalence`` age bands."""
    for key, value in (table or {}).items():
        try:
            lo_s, hi_s = str(key).split("-")
            lo, hi = int(lo_s), int(hi_s)
        except (ValueError, TypeError):
            continue
        if lo <= age <= hi:
            return float(value)
    return 0.0


def resolve_pregnancy_outcome(mother_id: str, mother_age: int, year: int) -> tuple[str, str]:
    """Decide whether a pregnancy conceived this year ends in
    ``"delivery"`` or ``"abortion"``. Returns ``(outcome, discharge_dx)``:

      * ``("delivery", "Z37.0")`` — proceed to the delivery event chain.
      * ``("abortion", "O03.9")`` — spontaneous abortion outcome.
      * ``("abortion", "O04.5")`` — induced abortion outcome.

    Consumes ONE per-(mother, year) sub-RNG (deterministic + isolated
    from the calendar / newborn RNGs). Consumers use the return to
    dispatch to ``simulate_delivery_encounter`` vs
    ``simulate_abortion_encounter``.
    """
    cfg = load_perinatal_config()
    ab_cfg = cfg.get("abortion") or {}
    p_abort = _lookup_age_band(ab_cfg.get("probability_by_age") or {}, mother_age)
    if p_abort <= 0.0:
        return ("delivery", "Z37.0")
    rng = np.random.default_rng(_abortion_outcome_sub_seed(mother_id, year))
    if float(rng.random()) >= p_abort:
        return ("delivery", "Z37.0")
    # Abortion outcome — split induced vs spontaneous.
    induced_share = _lookup_age_band(ab_cfg.get("induced_share_by_age") or {}, mother_age)
    return ("abortion", "O04.5" if float(rng.random()) < induced_share else "O03.9")


def simulate_abortion_encounter(
    patient: PatientProfile,
    visit_date: datetime,
    discharge_dx: str,
    roster: StaffRoster,
    rng: np.random.Generator,
    country: str = "US",
    config: object | None = None,  # noqa: ARG001 — enricher parity
    hospital_ops: dict | None = None,
) -> list[CIFPatientRecord]:
    """Emit a single outpatient (AMB) day-surgery abortion encounter for
    the mother. Discharge dx is ``O03.9`` (spontaneous) or ``O04.5``
    (induced) per ``resolve_pregnancy_outcome``. Newborn Patient
    chain is NOT emitted — abortion by definition does not produce a
    liveborn baby.

    Returns a list (of length 1) so the caller can treat delivery /
    abortion dispatch uniformly (both return ``list[CIFPatientRecord]``).
    """
    from clinosim.types.procedure import ProcedureRecord

    cfg = load_perinatal_config()
    ab_cfg = (cfg.get("abortion") or {}).get("encounter") or {}
    proc_cfg = (cfg.get("abortion") or {}).get("procedure") or {}

    dept = resolve_department(ab_cfg.get("department") or "obgyn", hospital_ops)
    encounter = create_inpatient_encounter(
        patient.patient_id,
        visit_date,
        chief_complaint=(ab_cfg.get("visit_reason") or {}).get("en") or "Pregnancy termination",
        department_id=dept,
        visit_number=0,
    )
    ja_reason = (ab_cfg.get("visit_reason") or {}).get("ja") or ""
    if ja_reason:
        encounter.chief_complaint_ja = ja_reason
    # AMB (outpatient day-surgery) — LOS < 1 day.
    encounter.encounter_type = EncounterType.OUTPATIENT
    encounter.status = EncounterStatus.COMPLETED
    duration_min = int(proc_cfg.get("duration_minutes") or 90)
    encounter.discharge_datetime = visit_date + timedelta(minutes=duration_min)
    encounter.admit_source = AdmitSource.OUTP
    encounter.discharge_disposition = DischargeDisposition.HOME
    encounter.priority = ActPriority.R

    staff = assign_staff("rounds", dept, roster, rng)
    encounter.attending_physician_id = staff.get("attending_physician", FALLBACK_PHYSICIAN_ID)
    encounter.admitting_physician_id = encounter.attending_physician_id
    encounter.discharging_physician_id = encounter.attending_physician_id

    # Admission dx = O03 spontaneous or O04 induced (WHO parent); discharge
    # dx = the specific billable leaf resolved earlier.
    admit_dx = "O03" if discharge_dx.startswith("O03") else "O04"
    icd_system = system_key_for("diagnosis", country)
    clinical_diagnosis = ClinicalDiagnosis(
        admission_diagnosis_code=admit_dx,
        admission_diagnosis_system=icd_system,
        discharge_diagnosis_code=discharge_dx,
        discharge_diagnosis_system=icd_system,
    )
    condition_event = ConditionEvent(
        condition_id=f"COND-{patient.patient_id}-ABORTION",
        condition_type="pregnancy_termination",
        ground_truth_diseases=[discharge_dx],
    )

    proc_code_jp = str(proc_cfg.get("jp_code") or "K909")
    proc_code_us = str(proc_cfg.get("us_code") or "59840")
    proc_code = proc_code_jp if is_jp(country) else proc_code_us
    procedure = ProcedureRecord(
        procedure_id=f"PROC-{patient.patient_id}-ABORTION-{encounter.encounter_id[:8]}",
        patient_id=patient.patient_id,
        encounter_id=encounter.encounter_id,
        procedure_type="pregnancy_termination",
        procedure_code=proc_code,
        procedure_code_jp=proc_code_jp,
        procedure_code_us=proc_code_us,
        start_datetime=visit_date,
        end_datetime=visit_date + timedelta(minutes=duration_min),
        primary_surgeon_id=encounter.attending_physician_id,
    )

    return [
        CIFPatientRecord(
            patient=patient,
            encounters=[encounter],
            orders=[],
            vital_signs=[],
            lab_results=[],
            procedures=[procedure],
            condition_event=condition_event,
            clinical_diagnosis=clinical_diagnosis,
            discharge_prescription=None,
            physiological_states=[],
        )
    ]


def _newborn_conditions_sub_seed(mother_id: str) -> int:
    """Sibling sub-seed for the newborn's condition roll (jaundice,
    preterm, atopic dermatitis, diaper dermatitis, and the preterm-
    gated RDS). Isolated from ``_newborn_sub_seed`` so tuning the
    condition probabilities does not shift the newborn's sex draw."""
    salt = "clinosim:newborn-conditions:v1"
    digest = hashlib.sha256(f"{salt}|{mother_id}".encode()).digest()[:6]
    return int.from_bytes(digest, "big") % (2**32)


def _sample_newborn_conditions(mother_id: str, delivery_date: date) -> list[ChronicCondition]:
    """Sample newborn perinatal conditions from ``perinatal.yaml::
    newborn_conditions``. Returns a list of ChronicCondition entries
    (each with ``onset_date = delivery_date``); the caller merges them
    onto the newborn's ``PatientProfile.chronic_conditions``.

    Per-mother sub-RNG (``_newborn_conditions_sub_seed``) makes the
    outcome deterministic per birth and RNG-neutral against every
    other patient in the cohort.
    """
    cfg = load_perinatal_config()
    entries = cfg.get("newborn_conditions") or []
    if not entries:
        return []
    rng = np.random.default_rng(_newborn_conditions_sub_seed(mother_id))
    onset = delivery_date
    out: list[ChronicCondition] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        code = str(entry.get("code") or "")
        if not code:
            continue
        prob = float(entry.get("probability") or 0.0)
        if float(rng.random()) >= prob:
            continue
        out.append(ChronicCondition(code=code, onset_date=onset))
        # Conditional triggers (e.g. preterm → RDS)
        for trig in entry.get("triggers") or []:
            if not isinstance(trig, dict):
                continue
            trig_code = str(trig.get("code") or "")
            trig_prob = float(trig.get("conditional_probability") or 0.0)
            if trig_code and float(rng.random()) < trig_prob:
                out.append(ChronicCondition(code=trig_code, onset_date=onset))
    return out


def _newborn_patient_id(mother_id: str) -> str:
    """Derive a stable newborn PatientId from the mother's ID. Format:
    ``<mother_id>-BABY`` — deterministic and mother-linkable via string
    inspection when needed. Multi-parity across a multi-year sim is
    still a scope limitation (each delivery reuses the same suffix); a
    ``period_seq``-based disambiguator is deferred to Incr 1.5."""
    return f"{mother_id}-BABY"


def _build_newborn_patient(mother: PatientProfile, delivery_date: date, sex: str) -> PatientProfile:
    """Build the newborn's PatientProfile — enough fields for the FHIR
    Patient emit to produce a valid resource (id, name, sex, DOB,
    household link inherited from mother, blood type omitted).

    Household inheritance: babies live with the mother, so
    ``household_id`` mirrors the mother's. Family name is inherited;
    given name is intentionally left empty (real newborns take days-
    to-weeks to receive a name and the CIF doesn't need to invent one
    for slice 2).
    """
    from clinosim.types.patient import Address, ContactInfo, PersonName

    newborn_id = _newborn_patient_id(mother.patient_id)
    return PatientProfile(
        patient_id=newborn_id,
        household_id=mother.household_id,
        name=PersonName(family_name=mother.name.family_name, given_name=""),
        age=0,
        sex=sex,
        date_of_birth=delivery_date,
        # Anthropometrics are age-appropriate infant defaults —
        # locale/shared/anthropometric_reference.yaml handles per-age
        # medians on emit; here we set the Layer-2 profile fallback
        # values so any consumer reading patient.height_cm / weight_kg
        # sees a plausible newborn (~50 cm / ~3.2 kg).
        height_cm=50.0,
        weight_kg=3.2,
        bmi=12.8,  # neonate BMI is not clinically meaningful but keeps the float non-zero
        address=Address(**{k: v for k, v in vars(mother.address).items()}) if mother.address else Address(),
        contact=ContactInfo(),
        preferred_language=mother.preferred_language,
        # Z38.0 (single liveborn) is universal; add the sampled newborn
        # conditions (jaundice / preterm / RDS gated on preterm / atopic
        # + diaper dermatitis) from ``perinatal.yaml::newborn_conditions``.
        chronic_conditions=[
            ChronicCondition(code="Z38.0", onset_date=delivery_date),
            *_sample_newborn_conditions(mother.patient_id, delivery_date),
        ],
    )


def simulate_delivery_encounter(
    patient: PatientProfile,
    visit_date: datetime,
    roster: StaffRoster,
    rng: np.random.Generator,
    country: str = "US",
    config: object | None = None,
    hospital_ops: dict | None = None,
) -> list[CIFPatientRecord]:
    """Build the delivery encounter chain: mother's IMP encounter +
    (Slice 2) the newborn's Patient + IMP Encounter + Z38.0.

    Returns a list so the caller (``simulator/engine.py`` delivery
    dispatch) can extend ``patient_records`` with every record the
    delivery produced. Slice-2 emits exactly two records: mother
    then newborn. If newborn Patient generation ever becomes
    optional (e.g. Z37.1 stillbirth), the list shape lets us return
    just the mother without breaking the caller.

    Mother-side shape:
      * ``class = "inpatient"``, admission_datetime = ``visit_date``,
        discharge_datetime = ``visit_date + LOS`` (LOS from
        ``perinatal.yaml.encounter.length_of_stay_days.{jp|us}``).
      * ``admission_diagnosis_code = "O80"`` (WHO ICD-10 single
        spontaneous delivery), ``discharge_diagnosis_code = "Z37.0"``
        (single liveborn, mother-side outcome).
      * One Procedure with the JP/US billing code from
        ``perinatal.yaml.procedure``.

    Newborn-side shape (Slice 2):
      * ``class = "inpatient"``, admission_datetime = delivery
        datetime, discharge_datetime = mother's discharge datetime
        (well-baby discharges with mother by convention).
      * ``admitSource = born``, ``partOf = <mother's delivery
        encounter>`` (FHIR mother→baby link).
      * ``discharge_diagnosis_code = "Z38.0"`` (single liveborn, born
        in hospital, delivered without mention of caesarean section).
      * Newborn Patient resource on the sibling patient list —
        ``household_id`` inherited from mother.
    """
    cfg = load_perinatal_config()
    enc_cfg = cfg.get("encounter") or {}
    proc_cfg = cfg.get("procedure") or {}

    dept = resolve_department(enc_cfg.get("department") or "obgyn", hospital_ops)

    # ── Mother-side delivery encounter ───────────────────────────────
    encounter = create_inpatient_encounter(
        patient.patient_id,
        visit_date,
        chief_complaint=(enc_cfg.get("visit_reason") or {}).get("en") or "Delivery",
        department_id=dept,
        visit_number=0,
    )
    ja_reason = (enc_cfg.get("visit_reason") or {}).get("ja") or ""
    if ja_reason:
        encounter.chief_complaint_ja = ja_reason
    encounter.encounter_type = EncounterType.INPATIENT
    encounter.status = EncounterStatus.COMPLETED
    los_days = int((enc_cfg.get("length_of_stay_days") or {}).get("jp" if is_jp(country) else "us") or 2)
    encounter.discharge_datetime = visit_date + timedelta(days=los_days)
    encounter.admit_source = AdmitSource.OUTP
    encounter.discharge_disposition = DischargeDisposition.HOME
    encounter.priority = ActPriority.R

    staff = assign_staff("rounds", dept, roster, rng)
    encounter.attending_physician_id = staff.get("attending_physician", FALLBACK_PHYSICIAN_ID)
    encounter.admitting_physician_id = encounter.attending_physician_id
    encounter.discharging_physician_id = encounter.attending_physician_id

    admit_dx = str(enc_cfg.get("admission_diagnosis_code") or "O80")
    discharge_dx = str(enc_cfg.get("discharge_diagnosis_code") or "Z37.0")
    icd_system = system_key_for("diagnosis", country)
    clinical_diagnosis = ClinicalDiagnosis(
        admission_diagnosis_code=admit_dx,
        admission_diagnosis_system=icd_system,
        discharge_diagnosis_code=discharge_dx,
        discharge_diagnosis_system=icd_system,
    )
    condition_event = ConditionEvent(
        condition_id=f"COND-{patient.patient_id}-DELIVERY",
        condition_type="perinatal_delivery",
        ground_truth_diseases=[discharge_dx],
    )

    from clinosim.types.procedure import ProcedureRecord

    proc_code_jp = str(proc_cfg.get("jp_code") or "K894")
    proc_code_us = str(proc_cfg.get("us_code") or "59400")
    proc_duration_min = int(proc_cfg.get("duration_minutes") or 90)
    proc_code = proc_code_jp if is_jp(country) else proc_code_us
    procedure = ProcedureRecord(
        procedure_id=f"PROC-{patient.patient_id}-DELIVERY-{encounter.encounter_id[:8]}",
        patient_id=patient.patient_id,
        encounter_id=encounter.encounter_id,
        procedure_type="delivery",
        procedure_code=proc_code,
        procedure_code_jp=proc_code_jp,
        procedure_code_us=proc_code_us,
        start_datetime=visit_date,
        end_datetime=visit_date + timedelta(minutes=proc_duration_min),
        primary_surgeon_id=encounter.attending_physician_id,
    )

    mother_record = CIFPatientRecord(
        patient=patient,
        encounters=[encounter],
        orders=[],
        vital_signs=[],
        lab_results=[],
        procedures=[procedure],
        condition_event=condition_event,
        clinical_diagnosis=clinical_diagnosis,
        discharge_prescription=None,
        physiological_states=[],
    )

    # ── Newborn-side chain (Slice 2 — Issue #957 Tier-3-B follow-up) ─
    # Per-mother sub-RNG for newborn sex (isolated from calendar RNG
    # so activating newborn emission does not shift any other patient's
    # stream).
    baby_rng = np.random.default_rng(_newborn_sub_seed(patient.patient_id))
    baby_sex = "M" if float(baby_rng.random()) < 0.514 else "F"  # ~51.4% male at birth (JP MHLW / US CDC)
    delivery_date = visit_date.date()
    newborn = _build_newborn_patient(patient, delivery_date, baby_sex)

    newborn_encounter = create_inpatient_encounter(
        newborn.patient_id,
        visit_date,
        chief_complaint="Newborn — born in hospital",
        department_id=dept,
        visit_number=0,
    )
    newborn_encounter.chief_complaint_ja = "新生児 — 院内出生"
    newborn_encounter.encounter_type = EncounterType.INPATIENT
    newborn_encounter.status = EncounterStatus.COMPLETED
    # Newborn stays with mother — same LOS.
    newborn_encounter.discharge_datetime = visit_date + timedelta(days=los_days)
    newborn_encounter.admit_source = AdmitSource.BORN
    newborn_encounter.discharge_disposition = DischargeDisposition.HOME
    newborn_encounter.priority = ActPriority.R
    # FHIR mother→baby link via Encounter.partOf on the newborn's encounter.
    newborn_encounter.admit_source_encounter_id = encounter.encounter_id
    newborn_encounter.attending_physician_id = encounter.attending_physician_id
    newborn_encounter.admitting_physician_id = encounter.attending_physician_id
    newborn_encounter.discharging_physician_id = encounter.attending_physician_id

    newborn_diagnosis = ClinicalDiagnosis(
        admission_diagnosis_code="Z38.0",  # single liveborn, born in hospital, without cesarean
        admission_diagnosis_system=icd_system,
        discharge_diagnosis_code="Z38.0",
        discharge_diagnosis_system=icd_system,
    )
    newborn_condition_event = ConditionEvent(
        condition_id=f"COND-{newborn.patient_id}-BIRTH",
        condition_type="newborn_birth",
        ground_truth_diseases=["Z38.0"],
    )

    newborn_record = CIFPatientRecord(
        patient=newborn,
        encounters=[newborn_encounter],
        orders=[],
        vital_signs=[],
        lab_results=[],
        procedures=[],
        condition_event=newborn_condition_event,
        clinical_diagnosis=newborn_diagnosis,
        discharge_prescription=None,
        physiological_states=[],
    )

    records = [mother_record, newborn_record]

    # POST_ENCOUNTER stage — session-98 F3 follow-up. Delivery + newborn
    # inpatient encounters previously skipped the enricher stage,
    # producing 4 IMP encounters / p=1000 (2 Z37.0 mothers + 2 Z38.0
    # newborns) with ZERO Compositions in the extended verify. Documents
    # / nursing / ADL / I/O are the exact EHR-record integrity signals a
    # downstream reader expects on ANY inpatient stay; birth admissions
    # are physically real inpatient stays. Guarded on ``config is not
    # None`` for test parity (the enricher stage requires config.country).
    if config is not None:
        from clinosim.simulator.enrichers import POST_ENCOUNTER, EnricherContext, run_stage

        # `config` is annotated `object | None` (kept for enricher-hook
        # parity), narrow to SimulatorConfig locally so mypy resolves
        # `config.random_seed`. Runtime callers always pass the concrete
        # SimulatorConfig instance via `simulator/engine.py::simulate`.
        _seed = int(getattr(config, "random_seed", 0))
        for _rec in records:
            run_stage(
                POST_ENCOUNTER,
                EnricherContext(
                    config=config,
                    master_seed=_seed,
                    records=[_rec],
                    roster=roster,
                ),
            )

    return records
