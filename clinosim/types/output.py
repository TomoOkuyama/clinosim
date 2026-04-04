"""CIF (Clinosim Intermediate Format) output types."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime

from clinosim.types.clinical import ClinicalDiagnosis, ConditionEvent, PhysiologicalState
from clinosim.types.encounter import (
    Encounter, MedicationAdministration, Order, OrderResult,
    PrescriptionRecord, VitalSignRecord,
)
from clinosim.types.patient import PatientProfile


@dataclass
class CIFMetadata:
    clinosim_version: str = ""
    generation_timestamp: datetime = field(default_factory=datetime.now)
    random_seed: int = 0
    country: str = ""
    hospital_scale: str = ""
    simulation_period_start: date | None = None
    simulation_period_end: date | None = None
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
    procedures: list = field(default_factory=list)  # ProcedureRecord
    rehab_sessions: list = field(default_factory=list)  # RehabSession
    medication_administrations: list[MedicationAdministration] = field(default_factory=list)
    discharge_prescription: PrescriptionRecord | None = None
    icu_transferred: bool = False
    deceased: bool = False
    death_day: int | None = None

    # Hidden state (for validation/debugging, not exported to clinical formats)
    physiological_states: list[PhysiologicalState] = field(default_factory=list)


@dataclass
class CIFDataset:
    metadata: CIFMetadata = field(default_factory=CIFMetadata)
    patients: list[CIFPatientRecord] = field(default_factory=list)
