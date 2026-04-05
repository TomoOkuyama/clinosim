"""Patient types — profile, physiological profile, baseline vitals."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


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
class PersonName:
    """Country-appropriate name representation (AD-25)."""

    family_name: str = ""
    given_name: str = ""
    display_name: str = ""  # formatted for display (e.g., "Given Family" or "Family Given")
    name_script: str = "en"  # "ja" | "en"
    phonetic: str | None = None  # phonetic reading for languages that need it (e.g., katakana)


@dataclass
class ChronicCondition:
    code: str = ""
    name: str = ""
    onset_date: date | None = None
    severity: str = "mild"
    controlled: bool = True
    severity_score: float = 0.3


@dataclass
class Allergy:
    substance: str = ""
    reaction_type: str = "rash"
    severity: str = "mild"


@dataclass
class PatientProfile:
    """Full Layer 2 clinical profile."""

    patient_id: str = ""
    name: PersonName = field(default_factory=PersonName)
    age: int = 0
    sex: str = "M"
    date_of_birth: date | None = None
    blood_type: str = "A"
    rh_factor: str = "+"
    height_cm: float = 170.0
    weight_kg: float = 65.0
    bmi: float = 22.5

    employment_status: str = "retired"
    insurance_type: str = "NHI_employee"
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
