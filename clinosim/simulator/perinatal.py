"""Perinatal delivery encounter emission (Issue #957 Tier-3-B slice 1).

Mother-side delivery inpatient encounter for a Z34-carrying pregnant
woman. Slice-1 scope: one inpatient encounter with admission dx O80
(single spontaneous delivery), discharge dx Z37.0 (single liveborn —
mother-side birth outcome, sex-locked female-only in
``icd10_sex_restrictions.yaml``) plus a delivery Procedure record with
the JP/US billing code from ``perinatal.yaml``.

Newborn Patient generation, postpartum encounters, and Z38 (newborn
birth-outcome code emitted on the baby's record) remain a follow-up
slice — the multi-patient linked-Encounter architecture (mother→baby
partOf reference, cross-patient reference infrastructure) is a
separate, larger change.
"""

from __future__ import annotations

from datetime import datetime, timedelta

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
from clinosim.types.patient import PatientProfile
from clinosim.types.procedure import ProcedureRecord


def simulate_delivery_encounter(
    patient: PatientProfile,
    visit_date: datetime,
    roster: StaffRoster,
    rng: np.random.Generator,  # noqa: ARG001 — reserved for future per-cycle draws
    country: str = "US",
    config: object | None = None,  # noqa: ARG001 — reserved for enricher hook parity
    hospital_ops: dict | None = None,
) -> CIFPatientRecord:
    """Build one delivery inpatient encounter for a Z34-carrying woman.

    Encounter shape:
      * ``class = "inpatient"``, admission_datetime = ``visit_date``,
        discharge_datetime = ``visit_date + LOS`` (LOS from
        ``perinatal.yaml.encounter.length_of_stay_days.{jp|us}``).
      * ``admission_diagnosis_code = "O80"`` (WHO ICD-10 single
        spontaneous delivery), ``discharge_diagnosis_code = "Z37.0"``
        (single liveborn, mother-side outcome).
      * One Procedure with the JP/US billing code from
        ``perinatal.yaml.procedure``.

    No orders / labs / vitals / prescription in slice 1 — the
    encounter + discharge diagnosis + procedure is enough to close
    the "0 mother-side delivery encounters" gap. Later slices can
    layer on peripartum labs, newborn Patient, postpartum visits.
    """
    cfg = load_perinatal_config()
    enc_cfg = cfg.get("encounter") or {}
    proc_cfg = cfg.get("procedure") or {}

    dept = resolve_department(enc_cfg.get("department") or "obgyn", hospital_ops)
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

    return CIFPatientRecord(
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
