"""Layer-1 population record types (catchment generation).

Plain runtime data types (AD-18 @dataclass) shared between the population module and
the simulator. The behaviour-bearing containers (Household, PopulationRegistry) stay in
the population module; only the data records that cross module boundaries live here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from clinosim.types.identity import IdentityTimeline

__all__ = ["HospitalizationSummary", "PersonRecord", "LifeEvent"]


@dataclass
class HospitalizationSummary:
    """Compact record of a past hospitalization, persisted in Layer 1."""
    encounter_id: str
    disease_id: str
    admission_date: date
    discharge_date: date
    los_days: int
    outcome: str  # "discharged" | "deceased" | "transferred"
    discharge_diagnoses: list[str] = field(default_factory=list)  # ICD codes
    discharge_medications: list[str] = field(default_factory=list)  # drug names
    residual_inflammation: float = 0.0  # state at discharge
    residual_renal: float = 1.0  # state at discharge
    was_readmission: bool = False


@dataclass
class PersonRecord:
    """Layer 1 person record — lightweight but retains medical history."""
    person_id: str
    household_id: str
    age: int
    sex: str
    date_of_birth: date
    family_name: str = ""
    given_name: str = ""
    phonetic: str | None = None
    blood_type: str = "A"
    # Address and contact (shared at household level)
    postal_code: str = ""
    state: str = ""
    city: str = ""
    address_line: str = ""
    phone_home: str = ""
    phone_mobile: str = ""
    chronic_conditions: list[str] = field(default_factory=list)
    current_medications: list[str] = field(default_factory=list)  # active medications
    # Occupation category (drives work-related injury risk); see PatientProfile.occupation
    occupation: str = "other"
    # Lifestyle attributes (set at generation time; drive disease risk multipliers)
    bmi: float = 22.0
    smoking_status: str = "never"   # "never" | "former" | "current"
    alcohol_use: str = "none"       # "none" | "social" | "heavy"
    is_alive: bool = True
    care_seeking_threshold: float = 0.3
    has_visited_hospital: bool = False
    visit_count: int = 0
    last_discharge_date: date | None = None
    last_encounter_id: str | None = None
    last_disease_id: str | None = None
    hospitalization_history: list[HospitalizationSummary] = field(default_factory=list)
    # Resident identifier & insurance enrollment (AD-54); populated by a separate
    # post-generation pass (clinosim.modules.identity.assign_identities).
    identity: IdentityTimeline | None = None


@dataclass
class LifeEvent:
    person_id: str
    event_type: str  # "acute_disease_onset" | "chronic_exacerbation" | "trauma" |
    #                   "unknown_condition" | "chronic_visit" | "health_screening" |
    #                   "ed_visit" | "followup"
    timestamp: date
    severity: float = 0.5  # 0.0-1.0
    condition_type: str = "known_disease"  # "known_disease" | "mixed" | "unknown" |
    #                                        "chronic_followup" | "screening" | "ed_visit"
    disease_id: str = ""
    encounter_type: str = "inpatient"  # "inpatient" | "outpatient" | "emergency"
    requires_hospital: bool = False
    is_readmission: bool = False
    prior_encounter_id: str | None = None
    readmission_number: int = 0
    protocol_source: str = ""  # YAML file that defines this encounter's protocol
