"""Patient types — profile, physiological profile, baseline vitals."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from clinosim.types.identity import IdentityTimeline


@dataclass
class PatientPhysiologicalProfile:
    """Hidden constitutional parameters. Determined once, stable across visits."""

    immune_reactivity: float = 0.5
    drug_metabolism_rate: str = "normal"  # "poor" | "normal" | "rapid" | "ultra_rapid"
    renal_reserve: float = 0.8
    cardiac_reserve: float = 0.8
    hepatic_reserve: float = 0.85
    treatment_sensitivity: float = 1.0
    symptom_reporting_bias: float = 1.0
    delirium_susceptibility: float = 0.2
    dvt_susceptibility: float = 0.2


@dataclass
class BaselineVitals:
    """This person's normal values when healthy."""

    temperature: float = 36.5
    heart_rate: int = 72
    systolic_bp: int = 120
    diastolic_bp: int = 75
    respiratory_rate: int = 16
    spo2: float = 97.5


@dataclass
class Address:
    """Postal address."""
    postal_code: str = ""
    state: str = ""  # US: state, JP: prefecture
    city: str = ""
    line1: str = ""  # street address
    line2: str = ""  # apt/unit
    country: str = "US"


@dataclass
class ContactInfo:
    """Patient contact information."""
    phone_home: str = ""     # household landline
    phone_mobile: str = ""   # personal mobile
    phone_primary: str = ""  # which one to use (home or mobile)
    email: str = ""
    emergency_contact_name: str = ""
    emergency_contact_phone: str = ""
    emergency_contact_relationship: str = ""


@dataclass
class PersonName:
    """Country-appropriate name representation (AD-25)."""

    family_name: str = ""
    given_name: str = ""
    display_name: str = ""
    name_script: str = "en"
    phonetic: str | None = None


@dataclass
class ChronicCondition:
    code: str = ""
    system: str = "icd-10-cm"  # code system key (lookup via clinosim.codes)
    onset_date: date | None = None
    severity: str = "mild"
    controlled: bool = True
    severity_score: float = 0.3
    stage: str = ""  # e.g., "CKD G3a", "NYHA II", "HbA1c 7.2%"


@dataclass
class Allergy:
    substance: str = ""
    reaction_type: str = "rash"
    severity: str = "mild"


@dataclass
class PatientProfile:
    """Full Layer 2 clinical profile."""

    patient_id: str = ""
    household_id: str = ""  # carried from Layer 1; links family members (AD-54)
    name: PersonName = field(default_factory=PersonName)
    age: int = 0  # kept for backward compat; derived from date_of_birth in output
    sex: str = "M"
    date_of_birth: date | None = None
    blood_type: str = "A"
    rh_factor: str = "+"
    height_cm: float = 170.0
    weight_kg: float = 65.0
    bmi: float = 22.5

    address: Address = field(default_factory=Address)
    contact: ContactInfo = field(default_factory=ContactInfo)

    marital_status: str = ""  # "S" | "M" | "D" | "W" | "U" (HL7 v3-MaritalStatus)
    preferred_language: str = ""  # BCP-47 code: "en-US" | "ja-JP"

    employment_status: str = "retired"
    # Occupation category (drives work-related injury risk):
    # "manufacturing" | "construction" | "agriculture" | "healthcare" |
    # "service" | "office" | "transportation" | "education" |
    # "homemaker" | "student" | "retired" | "unemployed" | "other"
    occupation: str = "other"
    insurance_type: str = "NHI_employee"
    # Resident identifier & insurance enrollment (AD-54). Carried from Layer 1.
    # NOTE: identity.national.national_id is for internal use only — output adapters
    # MUST NOT emit it (privacy chokepoint).
    identity: IdentityTimeline | None = None
    race: str = ""       # OMB race category — US only: "white"|"black"|"asian"|"native_american"|"other"
    ethnicity: str = ""  # "hispanic" | "not_hispanic" — US only
    health_literacy: float = 0.7

    chronic_conditions: list[ChronicCondition] = field(default_factory=list)
    allergies: list[Allergy] = field(default_factory=list)
    current_medications: list[str] = field(default_factory=list)
    smoking_status: str = "never"
    alcohol_use: str = "none"

    physiological_profile: PatientPhysiologicalProfile = field(
        default_factory=PatientPhysiologicalProfile
    )
    baseline_vitals: BaselineVitals = field(default_factory=BaselineVitals)
