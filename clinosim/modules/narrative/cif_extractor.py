"""Extract clinical data from CIF for narrative generation.

Each extraction function takes a CIFPatientRecord and returns a dict
containing all data needed to generate that narrative type.

Returns None if the patient doesn't need that narrative type
(e.g., no inpatient encounter for Admission H&P).
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

from clinosim.codes import lookup as code_lookup
from clinosim.types.encounter import EncounterType

if TYPE_CHECKING:
    from clinosim.types.output import CIFPatientRecord


def extract_admission_hp_data(cif_record: CIFPatientRecord) -> dict | None:
    """Extract data for Admission H&P.

    Requires:
    - Inpatient encounter
    - Admission vitals (first vitals after admission)
    - Admission labs (within 4h of admission)
    - Admission diagnosis

    Returns:
        dict with keys: patient, encounter, admission_vitals, admission_labs,
                       admission_diagnosis, pmh
        None if no inpatient encounter
    """
    # Find first inpatient encounter
    inpatient_encounter = None
    for enc in cif_record.encounters:
        if enc.encounter_type == EncounterType.INPATIENT:
            inpatient_encounter = enc
            break

    if not inpatient_encounter:
        return None

    # Get admission vitals (first vital after admission)
    admission_vitals = None
    if cif_record.vital_signs:
        for vs in cif_record.vital_signs:
            if vs.timestamp >= inpatient_encounter.admission_datetime:
                admission_vitals = vs
                break

    # Get admission labs (within first 4 hours)
    admission_cutoff = inpatient_encounter.admission_datetime + timedelta(hours=4)
    admission_labs = [
        lab
        for lab in cif_record.lab_results
        if lab.result_datetime >= inpatient_encounter.admission_datetime
        and lab.result_datetime <= admission_cutoff
    ]

    # Resolve diagnosis code to display text
    admission_dx = (
        code_lookup(
            cif_record.clinical_diagnosis.admission_diagnosis_system,
            cif_record.clinical_diagnosis.admission_diagnosis_code,
            "en",
        )
        if cif_record.clinical_diagnosis.admission_diagnosis_code
        else "Unknown"
    )

    # PMH from patient profile (if available)
    pmh = getattr(cif_record.patient, "medical_history", [])

    return {
        "patient": cif_record.patient,
        "encounter": inpatient_encounter,
        "admission_vitals": admission_vitals,
        "admission_labs": admission_labs,
        "admission_diagnosis": admission_dx,
        "pmh": pmh,
    }


def extract_discharge_summary_data(cif_record: CIFPatientRecord) -> dict | None:
    """Extract data for Discharge Summary.

    Requires:
    - Inpatient encounter with discharge_datetime
    - Admission vitals and labs
    - Discharge vitals and labs
    - Admission and discharge diagnoses
    - Discharge medications

    Returns:
        dict with keys: patient, encounter, admission_vitals, admission_labs,
                       discharge_vitals, discharge_labs, admission_diagnosis,
                       discharge_diagnosis, discharge_medications, los_days
        None if no discharged inpatient encounter
    """
    # Find discharged inpatient encounter
    inpatient_encounter = None
    for enc in cif_record.encounters:
        if enc.encounter_type == EncounterType.INPATIENT and enc.discharge_datetime:
            inpatient_encounter = enc
            break

    if not inpatient_encounter:
        return None

    # Admission vitals (first after admission)
    admission_vitals = None
    if cif_record.vital_signs:
        for vs in cif_record.vital_signs:
            if vs.timestamp >= inpatient_encounter.admission_datetime:
                admission_vitals = vs
                break

    # Discharge vitals (last before discharge)
    discharge_vitals = None
    if cif_record.vital_signs and inpatient_encounter.discharge_datetime:
        for vs in reversed(cif_record.vital_signs):
            if vs.timestamp <= inpatient_encounter.discharge_datetime:
                discharge_vitals = vs
                break

    # Admission labs (within first 4h)
    admission_cutoff = inpatient_encounter.admission_datetime + timedelta(hours=4)
    admission_labs = [
        lab
        for lab in cif_record.lab_results
        if lab.result_datetime >= inpatient_encounter.admission_datetime
        and lab.result_datetime <= admission_cutoff
    ]

    # Discharge labs (within last 24h before discharge)
    discharge_labs = []
    if inpatient_encounter.discharge_datetime:
        discharge_cutoff = inpatient_encounter.discharge_datetime - timedelta(hours=24)
        discharge_labs = [
            lab
            for lab in cif_record.lab_results
            if lab.result_datetime >= discharge_cutoff
            and lab.result_datetime <= inpatient_encounter.discharge_datetime
        ]

    # Resolve diagnosis codes
    admission_dx = (
        code_lookup(
            cif_record.clinical_diagnosis.admission_diagnosis_system,
            cif_record.clinical_diagnosis.admission_diagnosis_code,
            "en",
        )
        if cif_record.clinical_diagnosis.admission_diagnosis_code
        else "Unknown"
    )

    discharge_dx = (
        code_lookup(
            cif_record.clinical_diagnosis.discharge_diagnosis_system,
            cif_record.clinical_diagnosis.discharge_diagnosis_code,
            "en",
        )
        if cif_record.clinical_diagnosis.discharge_diagnosis_code
        else admission_dx
    )

    # Discharge medications
    discharge_medications = []
    if cif_record.discharge_prescription:
        discharge_medications = [
            item.get("drug_name", "Unknown")
            for item in cif_record.discharge_prescription.items
        ]

    # Length of stay
    los_days = (
        inpatient_encounter.discharge_datetime - inpatient_encounter.admission_datetime
    ).days

    return {
        "patient": cif_record.patient,
        "encounter": inpatient_encounter,
        "admission_vitals": admission_vitals,
        "admission_labs": admission_labs,
        "discharge_vitals": discharge_vitals,
        "discharge_labs": discharge_labs,
        "admission_diagnosis": admission_dx,
        "discharge_diagnosis": discharge_dx,
        "discharge_medications": discharge_medications,
        "los_days": los_days,
    }


def extract_operative_note_data(cif_record: CIFPatientRecord) -> dict | None:
    """Extract data for Operative Note.

    Requires:
    - Procedure record (surgical procedure)
    - Pre-op and post-op diagnoses
    - Anesthesia type
    - Duration, EBL, findings, complications

    TODO: Implement proper extraction from CIF procedure data.
    Currently returns minimal data structure as placeholder.

    Returns:
        dict with keys: patient, procedure, encounter, preop_diagnosis,
                       postop_diagnosis, anesthesia_type, duration_minutes,
                       ebl_ml, findings, complications
        None if no surgical procedures
    """
    if not cif_record.procedures:
        return None

    # TODO: Implement logic to identify surgical vs bedside procedures
    # For now, assume first procedure is surgical
    procedure = cif_record.procedures[0]

    # Find encounter containing this procedure
    encounter = None
    for enc in cif_record.encounters:
        # TODO: Match procedure.timestamp to encounter timeframe
        if enc.encounter_type == EncounterType.INPATIENT:
            encounter = enc
            break

    # TODO: Extract actual procedure details from CIF
    # Current CIF structure may not have all these fields
    # Need to enhance ProcedureRecord type or extract from other sources

    return {
        "patient": cif_record.patient,
        "procedure": procedure,
        "encounter": encounter,
        "preop_diagnosis": "TODO: Extract from CIF",
        "postop_diagnosis": "TODO: Extract from CIF",
        "anesthesia_type": "General anesthesia",
        "duration_minutes": getattr(procedure, "duration_minutes", 120),
        "ebl_ml": getattr(procedure, "ebl_ml", 0),
        "findings": "TODO: Extract from CIF",
        "complications": [],
    }


def extract_procedure_note_data(cif_record: CIFPatientRecord) -> dict | None:
    """Extract data for Procedure Note (bedside procedures).

    Requires:
    - Procedure record (non-surgical, bedside)
    - Indication, technique
    - Pre and post vitals
    - Complications

    TODO: Implement proper extraction from CIF procedure data.
    Currently returns minimal data structure as placeholder.

    Returns:
        dict with keys: patient, procedure, encounter, indication,
                       technique, complications, pre_vitals, post_vitals
        None if no procedures
    """
    if not cif_record.procedures:
        return None

    # TODO: Implement logic to identify bedside vs surgical procedures
    # For now, assume first procedure is bedside
    procedure = cif_record.procedures[0]

    # Find encounter containing this procedure
    encounter = None
    for enc in cif_record.encounters:
        # TODO: Match procedure.timestamp to encounter timeframe
        encounter = enc
        break

    # TODO: Extract actual procedure details from CIF
    # Get vitals before/after procedure timestamp

    return {
        "patient": cif_record.patient,
        "procedure": procedure,
        "encounter": encounter,
        "indication": "TODO: Extract from CIF",
        "technique": "TODO: Extract from CIF",
        "complications": [],
        "pre_vitals": None,
        "post_vitals": None,
    }


def extract_death_note_data(cif_record: CIFPatientRecord) -> dict | None:
    """Extract data for Death Note.

    Requires:
    - deceased = True
    - Encounter with discharge_disposition = "exp" (expired)
    - Cause of death (from diagnosis)
    - Death datetime
    - Hospital course summary

    Returns:
        dict with keys: patient, encounter, death_datetime, cause_of_death,
                       hospital_course_summary, complications
        None if patient not deceased
    """
    if not cif_record.deceased:
        return None

    # Find death encounter (discharge_disposition = "exp")
    death_encounter = None
    for enc in cif_record.encounters:
        if enc.discharge_disposition == "exp":
            death_encounter = enc
            break

    if not death_encounter:
        return None

    # Cause of death (use discharge diagnosis)
    cause_of_death = (
        code_lookup(
            cif_record.clinical_diagnosis.discharge_diagnosis_system,
            cif_record.clinical_diagnosis.discharge_diagnosis_code,
            "en",
        )
        if cif_record.clinical_diagnosis.discharge_diagnosis_code
        else "Unknown"
    )

    # TODO: Generate hospital course summary from CIF events
    # For now, provide minimal summary
    los_days = (
        death_encounter.discharge_datetime - death_encounter.admission_datetime
    ).days
    hospital_course_summary = (
        f"Patient was admitted and received intensive treatment for {los_days} days "
        "but condition deteriorated."
    )

    return {
        "patient": cif_record.patient,
        "encounter": death_encounter,
        "death_datetime": death_encounter.discharge_datetime,
        "cause_of_death": cause_of_death,
        "hospital_course_summary": hospital_course_summary,
        "complications": cif_record.complications_occurred,
    }
