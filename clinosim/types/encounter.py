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
    admission_datetime: datetime = field(default_factory=datetime.now)
    discharge_datetime: datetime | None = None
    chief_complaint: str = ""
    disease_event_id: str = ""
    time_resolution: timedelta | None = None

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
    measured_by: str = ""  # nurse staff_id
    data_source: str = "manual"  # "manual" | "device_auto"


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
