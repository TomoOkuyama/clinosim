"""CIF (Clinosim Intermediate Format) output types."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from clinosim.types.clinical import (
    ClinicalDiagnosis, ClinicalDocument, ConditionEvent, PhysiologicalState,
)
from clinosim.types.encounter import (
    ADLAssessment, Encounter, ImmunizationRecord, IntakeOutputRecord,
    MedicationAdministration, NursingRiskAssessment, Order, OrderResult,
    PrescriptionRecord, VitalSignRecord,
)
from clinosim.types.family_history import FamilyMemberHistoryRecord
from clinosim.types.microbiology import MicrobiologyResult
from clinosim.types.patient import PatientProfile
from clinosim.types.procedure import ProcedureRecord, RehabSession


@dataclass
class CIFMetadata:
    clinosim_version: str = ""
    generation_timestamp: datetime = field(default_factory=datetime.now)
    random_seed: int = 0
    country: str = ""
    hospital_scale: str = ""
    simulation_period_start: date | None = None
    simulation_period_end: date | None = None
    snapshot_date: str | None = None  # YYYY-MM-DD; current-state cutoff
    total_patients_generated: int = 0
    llm_mode: str = "none"


@dataclass
class CIFPatientRecord:
    """Complete patient record for CIF. Contains ALL data layers."""

    patient: PatientProfile = field(default_factory=PatientProfile)
    encounters: list[Encounter] = field(default_factory=list)
    orders: list[Order] = field(default_factory=list)
    vital_signs: list[VitalSignRecord] = field(default_factory=list)
    lab_results: list[OrderResult] = field(default_factory=list)

    # Condition & diagnosis (AD-28)
    condition_event: ConditionEvent = field(default_factory=ConditionEvent)
    clinical_diagnosis: ClinicalDiagnosis = field(default_factory=ClinicalDiagnosis)
    complications_occurred: list[str] = field(default_factory=list)
    procedures: list[ProcedureRecord] = field(default_factory=list)
    rehab_sessions: list[RehabSession] = field(default_factory=list)
    documents: list[ClinicalDocument] = field(default_factory=list)  # ClinicalDocument stubs (text="" in Stage 1)
    medication_administrations: list[MedicationAdministration] = field(default_factory=list)
    intake_output_records: list[IntakeOutputRecord] = field(default_factory=list)
    adl_assessments: list[ADLAssessment] = field(default_factory=list)
    nursing_risk_assessments: list[NursingRiskAssessment] = field(default_factory=list)
    immunizations: list[ImmunizationRecord] = field(default_factory=list)
    family_history: list[FamilyMemberHistoryRecord] = field(default_factory=list)  # AD-55 Base (codes only)
    microbiology: list[MicrobiologyResult] = field(default_factory=list)  # AD-55 Base (codes only)
    discharge_prescription: PrescriptionRecord | None = None
    icu_transferred: bool = False
    deceased: bool = False
    death_day: int | None = None

    # Readmission tracking
    is_readmission: bool = False
    prior_encounter_id: str | None = None
    readmission_number: int = 0  # 0 = first admission, 1 = first readmission

    # Hidden state (for validation/debugging, not exported to clinical formats)
    physiological_states: list[PhysiologicalState] = field(default_factory=list)

    # Opt-in module data (AD-55/AD-56). Base data uses typed fields above; modules
    # write under extensions[<module_name>] so they never edit this core type.
    extensions: dict[str, Any] = field(default_factory=dict)


@dataclass
class CIFDataset:
    metadata: CIFMetadata = field(default_factory=CIFMetadata)
    patients: list[CIFPatientRecord] = field(default_factory=list)
    hospital_roster: list = field(default_factory=list)  # list[StaffMember]
    hospital_config: dict = field(default_factory=dict)  # ops yaml content
