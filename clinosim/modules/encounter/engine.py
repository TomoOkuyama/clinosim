"""Encounter engine — v0.1-alpha: linear inpatient workflow only.

Generates the daily cycle timeline for a single inpatient encounter:
  Admission → Day 1..N (morning vitals/labs → rounds → afternoon → evening) → Discharge
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from clinosim.types.encounter import Encounter, EncounterStatus, EncounterType


@dataclass
class DailyCycleEvent:
    """A scheduled event within the daily cycle."""

    timestamp: datetime
    event_type: str  # "morning_vitals" | "morning_labs" | "rounds" | "afternoon_vitals" | "evening_vitals" | "evening_meds" | "night_check"
    data: dict[str, Any] = field(default_factory=dict)


def create_inpatient_encounter(
    patient_id: str,
    admission_datetime: datetime,
    chief_complaint: str = "Fever, cough, dyspnea",
    department_id: str = "internal_medicine",
) -> Encounter:
    """Create a new inpatient encounter."""
    return Encounter(
        encounter_id=f"ENC-{patient_id}-001",
        patient_id=patient_id,
        episode_id=f"EP-{patient_id}-001",
        encounter_type=EncounterType.INPATIENT,
        status=EncounterStatus.IN_PROGRESS,
        department_id=department_id,
        attending_physician_id="STAFF-PLACEHOLDER-001",
        admission_datetime=admission_datetime,
        chief_complaint=chief_complaint,
        disease_event_id=f"DE-{patient_id}-001",
        time_resolution=timedelta(hours=1),
    )


def generate_daily_cycle(encounter: Encounter, day_number: int) -> list[DailyCycleEvent]:
    """Generate the scheduled events for one inpatient day.

    Day structure (Japan, medium hospital):
      06:00-06:30  Morning vitals
      06:30-07:30  Morning lab draw
      09:00-11:00  Physician rounds
      14:00        Afternoon vitals
      18:00        Evening vitals + evening meds
      22:00        Night check
    """
    base_date = encounter.admission_datetime.date() + timedelta(days=day_number)
    events: list[DailyCycleEvent] = []

    def at(hour: int, minute: int = 0) -> datetime:
        return datetime(base_date.year, base_date.month, base_date.day, hour, minute)

    # Morning vitals
    events.append(DailyCycleEvent(
        timestamp=at(6, 0),
        event_type="morning_vitals",
    ))

    # Morning lab draw (if ordered)
    events.append(DailyCycleEvent(
        timestamp=at(6, 30),
        event_type="morning_labs",
    ))

    # Physician rounds
    events.append(DailyCycleEvent(
        timestamp=at(9, 0),
        event_type="rounds",
        data={"day_number": day_number},
    ))

    # Afternoon vitals
    events.append(DailyCycleEvent(
        timestamp=at(14, 0),
        event_type="afternoon_vitals",
    ))

    # Evening vitals + medications
    events.append(DailyCycleEvent(
        timestamp=at(18, 0),
        event_type="evening_vitals",
    ))

    events.append(DailyCycleEvent(
        timestamp=at(18, 30),
        event_type="evening_meds",
    ))

    # Night check (sparse)
    events.append(DailyCycleEvent(
        timestamp=at(22, 0),
        event_type="night_check",
    ))

    return events


def generate_encounter_timeline(
    encounter: Encounter,
    total_days: int,
) -> list[DailyCycleEvent]:
    """Generate the full timeline of events for an inpatient stay.

    Includes admission events (Day 0) and daily cycles for each day.
    """
    timeline: list[DailyCycleEvent] = []

    # Admission events (Day 0, at admission time)
    adm = encounter.admission_datetime
    timeline.append(DailyCycleEvent(
        timestamp=adm,
        event_type="admission",
    ))
    timeline.append(DailyCycleEvent(
        timestamp=adm + timedelta(minutes=30),
        event_type="admission_assessment",
    ))
    timeline.append(DailyCycleEvent(
        timestamp=adm + timedelta(hours=1),
        event_type="admission_orders",
    ))

    # Daily cycles
    for day in range(total_days):
        daily_events = generate_daily_cycle(encounter, day)
        # Skip events before admission time on Day 0
        for event in daily_events:
            if event.timestamp >= adm:
                timeline.append(event)

    # Discharge events (last day)
    discharge_date = encounter.admission_datetime.date() + timedelta(days=total_days)
    timeline.append(DailyCycleEvent(
        timestamp=datetime(discharge_date.year, discharge_date.month, discharge_date.day, 10, 0),
        event_type="discharge_decision",
    ))
    timeline.append(DailyCycleEvent(
        timestamp=datetime(discharge_date.year, discharge_date.month, discharge_date.day, 14, 0),
        event_type="discharge",
    ))

    # Sort chronologically
    timeline.sort(key=lambda e: e.timestamp)

    return timeline
