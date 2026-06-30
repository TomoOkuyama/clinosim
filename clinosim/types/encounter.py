"""Encounter and event types."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from enum import Enum


class EncounterType(str, Enum):
    OUTPATIENT = "outpatient"
    EMERGENCY = "emergency"
    INPATIENT = "inpatient"
    ICU = "icu"
    DAY_SURGERY = "day_surgery"
    REHAB_INPATIENT = "rehab_inpatient"
    PRENATAL_VISIT = "prenatal_visit"
    DELIVERY = "delivery"
    NICU = "nicu"


class EncounterStatus(str, Enum):
    PLANNED = "planned"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


# Time resolution per encounter type
TIME_RESOLUTION: dict[EncounterType, timedelta | None] = {
    EncounterType.OUTPATIENT: None,  # snapshot
    EncounterType.EMERGENCY: timedelta(minutes=30),
    EncounterType.INPATIENT: timedelta(hours=1),
    EncounterType.ICU: timedelta(minutes=15),
    EncounterType.DAY_SURGERY: timedelta(minutes=30),
    EncounterType.REHAB_INPATIENT: timedelta(days=1),
    EncounterType.PRENATAL_VISIT: None,  # snapshot
    EncounterType.DELIVERY: timedelta(minutes=5),
    EncounterType.NICU: timedelta(minutes=15),
}


@dataclass
class Encounter:
    encounter_id: str = ""
    patient_id: str = ""
    episode_id: str = ""
    encounter_type: EncounterType = EncounterType.INPATIENT
    status: EncounterStatus = EncounterStatus.PLANNED
    department_id: str = ""
    attending_physician_id: str = ""
    admitting_physician_id: str = ""
    discharging_physician_id: str = ""
    admission_datetime: datetime = field(default_factory=datetime.now)
    discharge_datetime: datetime | None = None
    chief_complaint: str = ""
    disease_event_id: str = ""
    ward_id: str = ""  # e.g. "4W" (4th floor west)
    bed_number: str = ""  # e.g. "401-2"
    time_resolution: timedelta | None = None
    # FHIR-aligned hospitalization fields
    admit_source: str = ""  # "emd" | "hosp-trans" | "gp" | "mp" | "nursing" | "outp"
    discharge_disposition: str = ""  # "home" | "hosp" | "other-hcf" | "exp" | "snf"
    priority: str = ""  # "EM" (emergency) | "UR" (urgent) | "R" (routine)

    def __post_init__(self) -> None:
        if self.time_resolution is None:
            self.time_resolution = TIME_RESOLUTION.get(self.encounter_type)


class OrderType(str, Enum):
    LAB = "lab"
    IMAGING = "imaging"
    MEDICATION = "medication"
    PROCEDURE = "procedure"
    CONSULTATION = "consultation"
    DIET = "diet"
    THERAPY = "therapy"
    INFECTION_CONTROL = "infection_control"


class OrderStatus(str, Enum):
    PLACED = "placed"
    ACCEPTED = "accepted"
    IN_PROGRESS = "in_progress"
    RESULTED = "resulted"
    REVIEWED = "reviewed"
    CANCELLED = "cancelled"
    STOPPED = "stopped"  # PR3b-3: medication order discontinued (narrow / de-escalation)


@dataclass
class OrderResult:
    result_datetime: datetime = field(default_factory=datetime.now)
    performed_by: str = ""
    lab_name: str = ""  # display name of the test (e.g., "CRP", "WBC")
    value: float | str | None = None
    unit: str | None = None
    reference_range: str | None = None
    flag: str | None = None  # "H" | "L" | "critical"
    interpretation: str | None = None
    specimen_note: str | None = None


@dataclass
class MedicationAdministration:
    """Record of a single medication administration event (MAR entry)."""

    order_id: str = ""
    drug_name: str = ""
    scheduled_datetime: datetime = field(default_factory=datetime.now)
    actual_datetime: datetime | None = None
    status: str = "given"  # "given" | "held" | "refused" | "not_available"
    dose: str = ""
    route: str = ""  # "IV" | "PO" | "SC" | "IM"
    administered_by: str = ""  # nurse staff_id
    hold_reason: str | None = None
    refusal_reason: str | None = None


@dataclass
class PrescriptionRecord:
    """Discharge or outpatient prescription record."""

    prescription_id: str = ""
    patient_id: str = ""
    prescriber_id: str = ""
    issue_date: datetime = field(default_factory=datetime.now)
    items: list[dict] = field(default_factory=list)
    # Each item: {drug_name, dose, frequency, route, days_supply, generic_name}


@dataclass
class Order:
    order_id: str = ""
    encounter_id: str = ""
    patient_id: str = ""
    order_type: OrderType = OrderType.LAB
    order_code: str = ""
    display_name: str = ""
    urgency: str = "routine"
    clinical_intent: str = ""
    ordered_datetime: datetime = field(default_factory=datetime.now)
    ordered_by: str = ""
    status: OrderStatus = OrderStatus.PLACED
    result: OrderResult | None = None
    # Structured medication fields (populated when order_type=MEDICATION)
    dose_quantity: float | None = None  # numeric dose value
    dose_unit: str = ""  # "mg" | "g" | "mL" | "unit"
    frequency: str = ""  # "BID" | "TID" | "q8h" | "once" | "continuous"
    frequency_per_day: int | None = None  # times per day for FHIR timing
    route: str = ""  # "PO" | "IV" | "SC" | "IM" | "SL" | "topical"
    duration_days: int | None = None
    reason_condition: str = ""  # ICD code or condition reference
    # PR1: Panel-aware grouping for ServiceRequest emission.
    # Empty = stand-alone test (1 SR per Order). Non-empty = panel name
    # ("CBC"/"BMP"/"LFT"/"ABG"/"Lipid"/"Coag"/"UA") — Orders sharing the same
    # (encounter_id, panel_key, ordered_datetime) tuple emit a single ServiceRequest.
    panel_key: str = ""
    # PR2(Tier 1 #2 imaging chain)— imaging-only fields. LAB / MED / 他 OrderType
    # では default ("" / [])のまま、FHIR 出力に影響しない(no-op safe)。
    imaging_modality: str = ""              # DCM code(CR/CT/MR/US/NM/...)
    imaging_body_site_code: str = ""        # SNOMED body structure
    imaging_views: list[str] = field(default_factory=list)
    imaging_spec_meta: dict = field(default_factory=dict)  # abnormal_rate_by_severity etc. (Task 4)


@dataclass
class VitalSignRecord:
    timestamp: datetime = field(default_factory=datetime.now)
    temperature_celsius: float | None = None
    heart_rate: int | None = None
    systolic_bp: int | None = None
    diastolic_bp: int | None = None
    respiratory_rate: int | None = None
    spo2: float | None = None
    pain_score: int | None = None
    consciousness_level: str = "A"  # AVPU: A=Alert, V=Voice, P=Pain, U=Unresponsive (NEWS2)
    on_supplemental_oxygen: bool = False
    oxygen_flow_rate_lpm: float | None = None  # liters per minute, if on O2
    oxygen_delivery_device: str = ""  # "nasal_cannula" | "simple_mask" | "venturi" | "non-rebreather" | "HFNC" | "BiPAP" | "ventilator"
    nursing_note: str = ""  # brief nursing assessment
    measured_by: str = ""  # nurse staff_id
    data_source: str = "manual"  # "manual" | "device_auto"
    news2_score: int | None = None  # NEWS2 aggregate (0-20), derived from this vital set
    gcs_score: int | None = None    # Glasgow Coma Scale total (3-15)


@dataclass
class ADLAssessment:
    """Activities of Daily Living assessment (Barthel Index, scored 0-100)."""
    date: date = field(default_factory=date.today)
    barthel_score: int = 100  # 0=totally dependent, 100=fully independent
    feeding: int = 10  # 0/5/10
    bathing: int = 5  # 0/5
    grooming: int = 5  # 0/5
    dressing: int = 10  # 0/5/10
    bowel_control: int = 10  # 0/5/10
    bladder_control: int = 10  # 0/5/10
    toilet_use: int = 10  # 0/5/10
    transfers: int = 15  # 0/5/10/15
    mobility: int = 15  # 0/5/10/15
    stairs: int = 10  # 0/5/10


@dataclass
class NursingRiskAssessment:
    """Daily nursing risk assessment: Braden (pressure ulcer) + Morse (fall) scales."""
    date: date = field(default_factory=date.today)
    braden_total: int = 23          # 6-23; lower = higher pressure-ulcer risk
    braden_sensory: int = 4         # 1-4
    braden_moisture: int = 4        # 1-4
    braden_activity: int = 4        # 1-4
    braden_mobility: int = 4        # 1-4
    braden_nutrition: int = 4       # 1-4
    braden_friction: int = 3        # 1-3
    morse_total: int = 0            # 0-125
    fall_risk_level: str = "low"    # "low" | "moderate" | "high"


@dataclass
class IntakeOutputRecord:
    """Daily fluid balance record (nursing documentation)."""
    date: date = field(default_factory=date.today)
    intake_iv_ml: int = 0  # IV fluid
    intake_oral_ml: int = 0  # oral intake
    intake_other_ml: int = 0  # blood products, tube feeding
    output_urine_ml: int = 0
    output_drain_ml: int = 0  # surgical drain, NG tube
    output_other_ml: int = 0  # emesis, stool
    net_balance_ml: int = 0  # intake - output


@dataclass
class ImmunizationRecord:
    """A completed immunization (vaccine history). FHIR Immunization (AD-55 Base).

    CIF stores the CVX code only; display resolved at output via clinosim.codes (AD-30).
    """
    vaccine_cvx: str = ""
    occurrence_date: date = field(default_factory=date.today)
    status: str = "completed"
    primary_source: bool = True
    dose_number: int | None = None
