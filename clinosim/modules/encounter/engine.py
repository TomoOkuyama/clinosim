"""Encounter engine — v0.1-alpha: linear inpatient workflow only.

Generates the daily cycle timeline for a single inpatient encounter:
  Admission → Day 1..N (morning vitals/labs → rounds → afternoon → evening) → Discharge
"""

from __future__ import annotations

import hashlib
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


_ENCOUNTER_SUFFIX_MODULUS = 10**12  # 12 decimal digits


def _encounter_id_suffix(
    patient_id: str,
    admission_datetime: datetime,
    chief_complaint: str,
    department_id: str,
    visit_number: int,
) -> int:
    """Deterministic 12-digit id suffix, stable regardless of *other* encounters.

    F1 (session 49): previously a module-global sequential counter assigned
    the suffix, so an encounter's id depended on how many *unrelated*
    encounters (e.g. other patients' readmissions) had already been created
    earlier in the same ``run_beta()`` call. Two cursor runs (differing only
    in ``snapshot_date``) can process a different number of upstream events
    (e.g. one extra readmission becomes eligible on a later cursor), which
    silently shifted every downstream encounter_id by a constant offset —
    breaking cross-cursor byte identity even though the RNG streams feeding
    clinical content are already cursor-stable (see ``derive_phase_rng``).
    Deriving the suffix from a hash of this encounter's own identity instead
    makes it independent of processing order/count, so the identical
    encounter always gets the identical id regardless of cursor or unrelated
    sibling encounters.

    All 5 inputs are folded in (not just patient_id + admission_datetime):
    the outpatient calendar phase schedules a ``chronic_visit`` and a
    ``health_screening`` for the same patient from *independent* per-key
    RNG streams (AD-16), so their randomized visit minute can coincidentally
    collide even though they are different encounters. ``chief_complaint``
    usually differs between such visit kinds, so folding it in (along with
    department_id + visit_number) helps disambiguate — but inputs alone
    cannot rule out a collision, they just reduce its probability. The
    modulus is therefore 12 digits (10**12), not 6: a 6-digit suffix
    (10**6) was confirmed EMPIRICALLY to collide within a single patient at
    p=500 (two different chronic-visit dates hashed to the same suffix,
    silently aliasing two distinct encounters under a `dict[encounter_id]`
    lookup — exactly the kind of AD-31 uniqueness violation this module
    must prevent). 12 digits keeps expected collisions negligible even for
    patients accumulating dozens of encounters across a multi-year
    incremental-snapshot cron history. The id only needs to be unique
    *within one patient* (already namespaced by ``patient_id`` in the
    caller).
    """
    key = (
        f"{patient_id}|{admission_datetime.isoformat()}"
        f"|{chief_complaint}|{department_id}|{visit_number}"
    )
    digest = hashlib.sha256(key.encode()).digest()[:6]
    return int.from_bytes(digest, "big") % _ENCOUNTER_SUFFIX_MODULUS


def create_inpatient_encounter(
    patient_id: str,
    admission_datetime: datetime,
    chief_complaint: str = "Fever, cough, dyspnea",
    department_id: str = "internal_medicine",
    visit_number: int = 1,
) -> Encounter:
    """Create a new encounter with a deterministic, cursor-independent ID."""
    enc_num = _encounter_id_suffix(
        patient_id, admission_datetime, chief_complaint, department_id, visit_number
    )
    enc_id = f"ENC-{patient_id}-{enc_num:012d}"
    return Encounter(
        encounter_id=enc_id,
        patient_id=patient_id,
        episode_id=f"EP-{patient_id}-{enc_num:012d}",
        encounter_type=EncounterType.INPATIENT,
        status=EncounterStatus.IN_PROGRESS,
        department_id=department_id,
        attending_physician_id="",
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
