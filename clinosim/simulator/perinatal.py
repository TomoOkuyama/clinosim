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


_NEWBORN_NAMING_WINDOW_DAYS: int = 14
"""Days after birth within which a Japanese newborn's given name is
typically not yet registered. 戸籍法第 49 条 mandates birth registration
within 14 days, and it is standard EHR practice for the given-name field
to stay empty (or a temporary placeholder) until then. After the window
the name is sampled from the locale's given-name pool. #1247."""


def _sample_newborn_given_name(baby_id: str, sex: str, country: str) -> str:
    """Deterministically sample a given name for a newborn from the same
    locale name pool used for adult patients (population.engine helpers).
    Uses a fresh sub-seed keyed on baby_id so the RNG cascade of the
    caller is untouched — the name is a pure derivative of (baby_id,
    country, sex).
    """
    from clinosim.modules.population.engine import _load_name_data, _sample_given_name

    name_data = _load_name_data(country)
    if not name_data:
        return ""
    # Sub-seed derived from baby_id — independent of any RNG stream so
    # perinatal callers see byte-identical output for their own draws.
    sub = int(hashlib.sha256(f"newborn-given|{baby_id}|{country}|{sex}".encode()).hexdigest(), 16) % (2**32)
    rng = np.random.default_rng(sub)
    picked = _sample_given_name(name_data, sex, rng)
    return str(picked.get("kanji") or picked.get("name") or "")


def _newborn_contact_from_mother(mother: PatientProfile):
    """Build a newborn `ContactInfo` seeded with the mother as the
    emergency contact (#1246). Direct telecom for the baby stays empty
    (a newborn cannot answer a phone); the mother's channels populate
    `emergency_contact_*` so downstream FHIR emit renders a
    `Patient.contact[]` entry with `relationship = MTH`.
    """
    from clinosim.types.patient import ContactInfo

    m_contact = getattr(mother, "contact", None) or ContactInfo()
    m_name = getattr(mother, "name", None)
    if m_name is not None:
        _display_parts = [str(getattr(m_name, "family_name", "") or "")]
        _given = str(getattr(m_name, "given_name", "") or "")
        if _given:
            _display_parts.append(_given)
        mother_name_text = " ".join(part for part in _display_parts if part)
    else:
        mother_name_text = ""
    emergency_phone = str(getattr(m_contact, "phone_mobile", "") or "") or str(
        getattr(m_contact, "phone_home", "") or ""
    )
    return ContactInfo(
        phone_home=str(getattr(m_contact, "phone_home", "") or ""),
        phone_mobile="",
        phone_primary=str(getattr(m_contact, "phone_home", "") or ""),
        email="",
        emergency_contact_name=mother_name_text,
        emergency_contact_phone=emergency_phone,
        emergency_contact_relationship="MTH" if (mother_name_text or emergency_phone) else "",
    )


def _build_newborn_patient(
    mother: PatientProfile,
    delivery_date: date,
    sex: str,
    snapshot_date: date | None = None,
    country: str = "US",
) -> PatientProfile:
    """Build the newborn's PatientProfile — enough fields for the FHIR
    Patient emit to produce a valid resource (id, name, sex, DOB,
    household link inherited from mother, blood type omitted).

    Household inheritance: babies live with the mother, so
    ``household_id`` mirrors the mother's. Family name is inherited.
    Given name (Issue #1247): empty within
    :data:`_NEWBORN_NAMING_WINDOW_DAYS` of birth (Japanese 戸籍法 window
    / US "Baby <family>" convention); sampled from the locale name pool
    afterwards. Requires ``snapshot_date`` — without it (test fixtures
    that predate this signature) the name stays empty, matching the
    pre-#1247 behaviour.
    """
    from clinosim.types.patient import Address, BaselineVitals, PersonName

    newborn_id = _newborn_patient_id(mother.patient_id)
    given = ""
    if snapshot_date is not None and (snapshot_date - delivery_date).days > _NEWBORN_NAMING_WINDOW_DAYS:
        given = _sample_newborn_given_name(newborn_id, sex, country)
    # Issue #1252 (N1): seed neonatal-specific `baseline_vitals` from
    # `perinatal.yaml::newborn.baseline_vitals` — term-newborn medians
    # (HR ~130 / BP ~68/40 / RR ~40) rather than the PatientProfile
    # adult defaults (HR 72 / BP 120/75 / RR 16). Same locale-config file
    # already carries every other newborn parameter (LOS / cesarean rate
    # / newborn conditions). Occupation defaults to the framework's
    # existing developmental-stage label "infant" (乳児 / Infant) rather
    # than the adult fallback "other" — same file, same section.
    _newborn_cfg = (load_perinatal_config() or {}).get("newborn") or {}
    _bv_cfg = _newborn_cfg.get("baseline_vitals") or {}
    baseline_vitals = BaselineVitals(
        temperature=float(_bv_cfg.get("temperature", 36.7)),
        heart_rate=int(_bv_cfg.get("heart_rate", 130)),
        systolic_bp=int(_bv_cfg.get("systolic_bp", 68)),
        diastolic_bp=int(_bv_cfg.get("diastolic_bp", 40)),
        respiratory_rate=int(_bv_cfg.get("respiratory_rate", 40)),
        spo2=float(_bv_cfg.get("spo2", 97)),
    )
    occupation = str(_newborn_cfg.get("occupation") or "infant")
    return PatientProfile(
        patient_id=newborn_id,
        household_id=mother.household_id,
        name=PersonName(family_name=mother.name.family_name, given_name=given),
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
        baseline_vitals=baseline_vitals,
        occupation=occupation,
        address=Address(**{k: v for k, v in vars(mother.address).items()}) if mother.address else Address(),
        # Issue #1246: newborns cannot be contacted directly (no personal
        # phone / email), so `Patient.telecom` stays empty — but every
        # real pediatric EHR carries the parent's phone as the emergency
        # contact so the baby is reachable via the guardian. Inherit the
        # mother's contact channels:
        #   * `phone_home` — household landline is shared (baby lives at
        #     the same address), so the number is copied verbatim.
        #   * `phone_mobile` / `email` — personal channels, left empty.
        #   * `emergency_contact_*` — mother's name + preferred phone,
        #     relationship = "MTH" (the delivery path is mother-only;
        #     father / other guardian is a follow-up scope).
        contact=_newborn_contact_from_mother(mother),
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

    # ── Cesarean-section roll (session 98 F7 — Incr 1.5) ─────────────
    # Real-world share: US 32.1 %, JP 20.4 %. Pre-fix all deliveries
    # emitted as O80 (spontaneous vaginal), which produced 100 %
    # vaginal cohorts — clinically unrealistic. Roll per-mother via
    # a dedicated sub-RNG (isolated from the main rng cursor so
    # activating this feature is byte-neutral for any non-perinatal
    # patient).
    cs_cfg = cfg.get("cesarean") or {}
    cs_prob = float((cs_cfg.get("probability") or {}).get("jp" if is_jp(country) else "us") or 0.0)
    cs_rng = np.random.default_rng(_newborn_sub_seed(f"cesarean|{patient.patient_id}"))
    is_cesarean = float(cs_rng.random()) < cs_prob

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
    if is_cesarean:
        cs_los = int((cs_cfg.get("length_of_stay_days") or {}).get("jp" if is_jp(country) else "us") or 4)
        los_days = cs_los
    else:
        los_days = int((enc_cfg.get("length_of_stay_days") or {}).get("jp" if is_jp(country) else "us") or 2)
    encounter.discharge_datetime = visit_date + timedelta(days=los_days)
    encounter.admit_source = AdmitSource.OUTP
    encounter.discharge_disposition = DischargeDisposition.HOME
    encounter.priority = ActPriority.R

    staff = assign_staff("rounds", dept, roster, rng)
    encounter.attending_physician_id = staff.get("attending_physician", FALLBACK_PHYSICIAN_ID)
    encounter.admitting_physician_id = encounter.attending_physician_id
    encounter.discharging_physician_id = encounter.attending_physician_id

    if is_cesarean:
        admit_dx = str(cs_cfg.get("admission_diagnosis_code") or "O82")
    else:
        admit_dx = str(enc_cfg.get("admission_diagnosis_code") or "O80")
    # discharge diagnosis Z37.0 (single liveborn — outcome) applies to
    # both delivery modes; ICD-10 does not sub-divide Z37 by mode.
    discharge_dx = str(enc_cfg.get("discharge_diagnosis_code") or "Z37.0")
    icd_system = system_key_for("diagnosis", country)

    # Issue #1285: surface pre-sampled pregnancy complications on the
    # delivery encounter. `_pregnancy_lifecycle_events` (population/
    # engine.py) samples per-pregnancy Bernoulli complications at
    # conception (from `perinatal.yaml::complications.bernoulli_draws`)
    # and stores them on the pregnancy `TemporalStatePeriod.metadata`.
    # The delivery encounter reads them back and renders them as:
    #   * secondary working_diagnoses entries — FHIR emit picks these
    #     up as secondary Conditions attached to the delivery encounter
    #     (same shape used by in-hospital complication tracking, see
    #     ``simulator/engine.py::_record_complication_on_active_encounter``);
    #   * additional ground_truth_diseases entries on the ConditionEvent
    #     so downstream consumers see the actual clinical burden.
    # Aborted pregnancies never reach this builder, so no O-chapter
    # complication codes leak into an abortion event.
    complications: list[str] = []
    for period in getattr(patient, "state_periods", []) or []:
        if getattr(period, "state_type", "") != "pregnancy":
            continue
        if getattr(period, "outcome", "") == "aborted":
            continue
        meta = getattr(period, "metadata", {}) or {}
        pd = meta.get("planned_delivery_date")
        # Match this delivery to its own pregnancy period. A patient can
        # accumulate multiple periods across sim years — pick the one
        # whose planned_delivery_date matches visit_date.
        if isinstance(pd, date) and pd == visit_date.date():
            complications = [str(c) for c in (meta.get("complications") or []) if c]
            break

    working_diagnoses: list[dict] = []
    for code in complications:
        working_diagnoses.append(
            {
                "disease_id": code,
                "onset_day": 0,
                "onset_datetime": visit_date.isoformat(),
            }
        )

    clinical_diagnosis = ClinicalDiagnosis(
        admission_diagnosis_code=admit_dx,
        admission_diagnosis_system=icd_system,
        discharge_diagnosis_code=discharge_dx,
        discharge_diagnosis_system=icd_system,
        working_diagnoses=working_diagnoses,
    )
    condition_event = ConditionEvent(
        condition_id=f"COND-{patient.patient_id}-DELIVERY",
        condition_type=("mixed" if complications else "perinatal_delivery"),
        ground_truth_diseases=[discharge_dx, *complications],
    )

    from clinosim.types.procedure import ProcedureRecord

    if is_cesarean:
        cs_proc = cs_cfg.get("procedure") or {}
        proc_code_jp = str(cs_proc.get("jp_code") or "K898")
        proc_code_us = str(cs_proc.get("us_code") or "59510")
        proc_duration_min = int(cs_proc.get("duration_minutes") or 60)
    else:
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

    # Issue #1285: emit the full cesarean intraoperative medication
    # bundle. Real-world US C-section deliveries are covered by ACOG /
    # SCIP protocols with essentially 100 % compliance on:
    #   1. Cefazolin 2 g IV single dose within 60 min preop
    #      (SCIP-INF-1 antimicrobial prophylaxis).
    #   2. Bupivacaine 0.5 % 12 mg intrathecal (spinal anesthesia,
    #      the dominant anesthetic modality for elective C-section).
    #   3. Fentanyl 25 mcg intrathecal adjunct (opioid potentiation
    #      of the spinal block).
    #   4. Ondansetron 4 mg IV pre-incision (5HT3 antiemetic
    #      prophylaxis against spinal-induced hypotension nausea).
    #   5. Oxytocin 10 U IV bolus after cord clamp (uterotonic
    #      to promote uterine contraction + prevent PPH).
    #   6. Ketorolac 30 mg IV postop (multimodal analgesia adjunct
    #      to opioid, per ERAS obstetric pathway).
    # Pre-fix (p=10k s=354): 37 US C-sections emitted zero of these
    # meds. Drug codes registered 2026-09-12 (RxNorm + JP YJ) so
    # `MedicationRequest.medicationCodeableConcept.coding` populates.
    #
    # Timing anchors: Cefazolin 30 min preop; bupivacaine + fentanyl +
    # ondansetron at time of incision (visit_date); oxytocin at cord
    # clamp (~10 min after incision, typical); ketorolac 60 min postop.
    #
    # Determinism: pure deterministic emissions (fixed doses, fixed
    # timing anchors relative to visit_date). No RNG consumption.
    orders: list = []
    if is_cesarean:
        from clinosim.types.encounter import Order, OrderStatus, OrderType

        _attending = encounter.attending_physician_id
        _cs_ord_specs: list[tuple[str, str, str, str, float, str, str, timedelta]] = [
            # (id_suffix, display_name, intent_en, intent_ja, dose, unit, route, timing_delta)
            (
                "CSCF",
                "Cefazolin",
                "Cesarean surgical antimicrobial prophylaxis (ACOG / SCIP-INF-1)",
                "帝王切開周術期予防抗菌薬 (ACOG / SCIP-INF-1)",
                2.0,
                "g",
                "IV",
                timedelta(minutes=-30),
            ),
            (
                "CSBP",
                "Bupivacaine",
                "Cesarean spinal anesthesia (0.5 % intrathecal)",
                "帝王切開脊髄くも膜下麻酔 (0.5 % 髄腔内)",
                12.0,
                "mg",
                "IT",
                timedelta(minutes=0),
            ),
            (
                "CSFN",
                "Fentanyl",
                "Cesarean intrathecal opioid adjunct to spinal anesthesia",
                "帝王切開脊髄くも膜下麻酔 オピオイド補助",
                25.0,
                "mcg",
                "IT",
                timedelta(minutes=0),
            ),
            (
                "CSOD",
                "Ondansetron",
                "Cesarean antiemetic prophylaxis (spinal-induced hypotension)",
                "帝王切開制吐薬予防 (脊麻後低血圧対策)",
                4.0,
                "mg",
                "IV",
                timedelta(minutes=0),
            ),
            (
                "CSOX",
                "Oxytocin",
                "Cesarean uterotonic post-cord-clamp (PPH prevention)",
                "帝王切開臍帯クランプ後 子宮収縮薬 (PPH予防)",
                10.0,
                "U",
                "IV",
                timedelta(minutes=10),
            ),
            (
                "CSKT",
                "Ketorolac",
                "Cesarean postoperative multimodal analgesia (ERAS)",
                "帝王切開術後多剤鎮痛 (ERAS)",
                30.0,
                "mg",
                "IV",
                timedelta(minutes=60),
            ),
        ]
        for _sfx, _name, _intent_en, _intent_ja, _dose, _unit, _route, _delta in _cs_ord_specs:
            orders.append(
                Order(
                    order_id=f"ORD-{encounter.encounter_id}-{_sfx}-01",
                    encounter_id=encounter.encounter_id,
                    patient_id=patient.patient_id,
                    order_type=OrderType.MEDICATION,
                    display_name=_name,
                    urgency="stat",
                    clinical_intent=_intent_en,
                    clinical_intent_ja=_intent_ja,
                    ordered_datetime=visit_date + _delta,
                    ordered_by=_attending,
                    status=OrderStatus.PLACED,
                    dose_quantity=_dose,
                    dose_unit=_unit,
                    frequency="once",
                    frequency_per_day=1,
                    route=_route,
                    duration_days=1,
                )
            )

    mother_record = CIFPatientRecord(
        patient=patient,
        encounters=[encounter],
        orders=orders,
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
    # Issue #1247: pass snapshot_date so `_build_newborn_patient` decides
    # given-name assignment (empty within 14 days of birth per JP 戸籍法,
    # sampled from the locale name pool afterwards). `config.snapshot_date`
    # is a `date` (or None on test paths without a config).
    _snap = getattr(config, "snapshot_date", None) if config is not None else None
    if isinstance(_snap, str):
        try:
            _snap = date.fromisoformat(_snap[:10])
        except ValueError:
            _snap = None
    newborn = _build_newborn_patient(patient, delivery_date, baby_sex, snapshot_date=_snap, country=country)

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
