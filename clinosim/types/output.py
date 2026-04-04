"""CIF (Clinosim Intermediate Format) output types."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime

from clinosim.types.clinical import ClinicalDiagnosis, ConditionEvent, PhysiologicalState
from clinosim.types.encounter import Encounter, Order, OrderResult, VitalSignRecord
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
    deceased: bool = False  # did the patient die during this encounter?
    death_day: int | None = None  # hospital day of death (None if survived)

    # Hidden state (for validation/debugging, not exported to clinical formats)
    physiological_states: list[PhysiologicalState] = field(default_factory=list)


@dataclass
class CIFDataset:
    metadata: CIFMetadata = field(default_factory=CIFMetadata)
    patients: list[CIFPatientRecord] = field(default_factory=list)
