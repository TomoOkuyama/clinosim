"""Discrete-Event Simulation (DES) engine.

Time advances globally. All patients share hospital resources.
Delays emerge from resource contention, not hardcoded values.

Usage:
    engine = DESEngine(config, hospital_ops)
    engine.seed_events(population, acute_events, calendar_events)
    dataset = engine.run()
"""

from __future__ import annotations

import heapq
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

import numpy as np

from clinosim.modules.facility.hospital_state import HospitalState
from clinosim.types.output import CIFPatientRecord


@dataclass(order=True)
class SimEvent:
    """A single simulation event, ordered by time."""

    time: datetime
    priority: int = field(default=0, compare=True)  # lower = higher priority
    event_id: int = field(default=0, compare=True)
    patient_id: str = field(default="", compare=False)
    event_type: str = field(default="", compare=False)  # see EVENT_TYPES
    data: dict = field(default_factory=dict, compare=False)


# Event types:
# "admission"         - patient arrives at hospital
# "lab_order"         - lab test ordered
# "lab_result"        - lab result available
# "imaging_order"     - imaging ordered
# "imaging_result"    - imaging result available
# "medication_admin"  - medication given
# "vitals_check"      - vital signs measured
# "daily_assessment"  - morning rounds / daily evaluation
# "discharge_check"   - evaluate if ready for discharge
# "discharge"         - patient discharged
# "outpatient_visit"  - outpatient appointment
# "ed_visit"          - ED visit


class EventQueue:
    """Priority queue of SimEvents, ordered by time."""

    def __init__(self) -> None:
        self._heap: list[SimEvent] = []
        self._counter: int = 0

    def push(self, event: SimEvent) -> None:
        event.event_id = self._counter
        self._counter += 1
        heapq.heappush(self._heap, event)

    def pop(self) -> SimEvent:
        return heapq.heappop(self._heap)

    def is_empty(self) -> bool:
        return len(self._heap) == 0

    def __len__(self) -> int:
        return len(self._heap)


class PatientContext:
    """Tracks an active patient's state during their hospital stay."""

    def __init__(self, patient_id: str, encounter_type: str) -> None:
        self.patient_id = patient_id
        self.encounter_type = encounter_type  # "inpatient" | "outpatient" | "emergency"
        self.admission_time: datetime | None = None
        self.day: int = 0
        self.pending_labs: dict[str, datetime] = {}  # order_id → ordered_time
        self.pending_imaging: dict[str, datetime] = {}
        self.scenario_step: int = 0


class DESEngine:
    """Discrete-event simulation engine.

    Processes all events in chronological order across all patients.
    Hospital resources are shared — delays emerge from contention.
    """

    def __init__(
        self,
        rng: np.random.Generator,
        hospital_state: HospitalState,
        hospital_ops: dict[str, Any],
    ) -> None:
        self.rng = rng
        self.hospital = hospital_state
        self.ops = hospital_ops
        self.queue = EventQueue()
        self.active_patients: dict[str, PatientContext] = {}
        self.completed_records: list[CIFPatientRecord] = []
        self.current_time: datetime = datetime(2024, 1, 1)

        # Statistics
        self.events_processed: int = 0
        self.peak_concurrent_patients: int = 0

    def seed_events(self, events: list[SimEvent]) -> None:
        """Add initial events to the queue."""
        for event in events:
            self.queue.push(event)

    def run(self, max_events: int = 1_000_000) -> None:
        """Process all events in chronological order."""
        while not self.queue.is_empty() and self.events_processed < max_events:
            event = self.queue.pop()

            # Advance hospital time
            if event.time > self.current_time:
                self.current_time = event.time
                self.hospital.update_for_time(self.current_time, self.ops)

            # Process event
            new_events = self._process_event(event)
            for new_event in new_events:
                self.queue.push(new_event)

            self.events_processed += 1

            # Track concurrent patients
            n_active = len(self.active_patients)
            if n_active > self.peak_concurrent_patients:
                self.peak_concurrent_patients = n_active

            # Progress
            if self.events_processed % 1000 == 0:
                print(
                    f"  DES: {self.events_processed} events, "
                    f"{n_active} active patients, "
                    f"time={self.current_time.strftime('%Y-%m-%d %H:%M')}",
                    flush=True,
                )

    def _process_event(self, event: SimEvent) -> list[SimEvent]:
        """Process a single event. Returns follow-up events."""
        match event.event_type:
            case "admission":
                return self._handle_admission(event)
            case "lab_order":
                return self._handle_lab_order(event)
            case "lab_result":
                return self._handle_lab_result(event)
            case "imaging_order":
                return self._handle_imaging_order(event)
            case "daily_assessment":
                return self._handle_daily_assessment(event)
            case "discharge":
                return self._handle_discharge(event)
            case "outpatient_visit":
                return self._handle_outpatient(event)
            case "ed_visit":
                return self._handle_ed_visit(event)
            case _:
                return []

    def _handle_admission(self, event: SimEvent) -> list[SimEvent]:
        """Patient admitted. Check bed availability, generate initial orders."""
        pid = event.patient_id

        # Check bed occupancy
        if self.hospital.bed_occupancy >= 0.95:
            # Delay admission by 2-4 hours (ED boarding)
            delay = float(self.rng.normal(3, 1)) * 60  # minutes
            event.time += timedelta(minutes=max(30, delay))
            event.data["ed_boarding_hours"] = delay / 60
            return [event]  # re-queue with delay

        # Admit
        self.hospital.bed_occupancy += 1.0 / self.ops.get("resource_capacity", {}).get("inpatient_beds", 200)
        ctx = PatientContext(pid, "inpatient")
        ctx.admission_time = event.time
        self.active_patients[pid] = ctx

        # Generate initial lab orders (using hospital state for timing)
        follow_up: list[SimEvent] = []
        initial_labs = event.data.get("initial_labs", [])
        for i, lab in enumerate(initial_labs):
            follow_up.append(
                SimEvent(
                    time=event.time + timedelta(minutes=float(self.rng.normal(10, 5))),
                    priority=1,
                    patient_id=pid,
                    event_type="lab_order",
                    data={"test": lab, "urgency": "stat"},
                )
            )

        # Schedule first daily assessment (next morning 08:00)
        next_morning = event.time.replace(hour=8, minute=0, second=0)
        if event.time.hour >= 8:
            next_morning += timedelta(days=1)
        follow_up.append(
            SimEvent(
                time=next_morning,
                priority=5,
                patient_id=pid,
                event_type="daily_assessment",
                data={"day": 1},
            )
        )

        return follow_up

    def _handle_lab_order(self, event: SimEvent) -> list[SimEvent]:
        """Lab ordered. Calculate delay from hospital state, schedule result."""
        delay = self.hospital.calculate_delay("lab", event.data.get("urgency", "routine"), self.ops)
        delay *= float(1.0 + self.rng.normal(0, 0.15))  # ±15% randomness
        delay = max(10.0, delay)

        self.hospital.add_to_queue("lab", self.ops)

        return [
            SimEvent(
                time=event.time + timedelta(minutes=delay),
                priority=2,
                patient_id=event.patient_id,
                event_type="lab_result",
                data={"test": event.data.get("test", ""), "ordered_at": event.time},
            )
        ]

    def _handle_lab_result(self, event: SimEvent) -> list[SimEvent]:
        """Lab result available. Release resource."""
        self.hospital.release_from_queue("lab", self.ops)
        # Result processing is handled by the inpatient simulator
        return []

    def _handle_imaging_order(self, event: SimEvent) -> list[SimEvent]:
        """Imaging ordered. Calculate delay from hospital state."""
        test = event.data.get("test", "xray").lower()
        if "ct" in test:
            resource = "ct"
        elif "mri" in test:
            resource = "mri"
        elif "ultra" in test or "echo" in test:
            resource = "ultrasound"
        else:
            resource = "xray"

        delay = self.hospital.calculate_delay(resource, event.data.get("urgency", "routine"), self.ops)
        delay *= float(1.0 + self.rng.normal(0, 0.2))
        delay = max(15.0, delay)

        self.hospital.add_to_queue(resource, self.ops)

        return [
            SimEvent(
                time=event.time + timedelta(minutes=delay),
                priority=2,
                patient_id=event.patient_id,
                event_type="imaging_result",
                data={"test": test, "ordered_at": event.time},
            )
        ]

    def _handle_daily_assessment(self, event: SimEvent) -> list[SimEvent]:
        """Morning rounds. Evaluate state, order labs, check discharge."""
        pid = event.patient_id
        ctx = self.active_patients.get(pid)
        if not ctx:
            return []

        ctx.day = event.data.get("day", ctx.day + 1)
        follow_up: list[SimEvent] = []

        # Daily lab orders
        daily_labs = event.data.get("daily_labs", ["CRP", "WBC", "Creatinine"])
        for lab in daily_labs:
            follow_up.append(
                SimEvent(
                    time=event.time + timedelta(minutes=float(self.rng.normal(5, 3))),
                    priority=3,
                    patient_id=pid,
                    event_type="lab_order",
                    data={"test": lab, "urgency": "routine"},
                )
            )

        # Schedule next daily assessment (tomorrow 08:00)
        follow_up.append(
            SimEvent(
                time=event.time + timedelta(days=1),
                priority=5,
                patient_id=pid,
                event_type="daily_assessment",
                data={"day": ctx.day + 1, "daily_labs": daily_labs},
            )
        )

        return follow_up

    def _handle_discharge(self, event: SimEvent) -> list[SimEvent]:
        """Patient discharged. Free bed."""
        pid = event.patient_id
        if pid in self.active_patients:
            del self.active_patients[pid]
        beds = self.ops.get("resource_capacity", {}).get("inpatient_beds", 200)
        self.hospital.bed_occupancy = max(0, self.hospital.bed_occupancy - 1.0 / beds)
        return []

    def _handle_outpatient(self, event: SimEvent) -> list[SimEvent]:
        """Outpatient visit. Brief, uses minimal resources."""
        # Outpatient visits don't occupy beds but may use lab/imaging
        return []

    def _handle_ed_visit(self, event: SimEvent) -> list[SimEvent]:
        """ED visit. Uses ED bed, may use lab/imaging."""
        return []

    def stats(self) -> dict[str, Any]:
        return {
            "events_processed": self.events_processed,
            "peak_concurrent_patients": self.peak_concurrent_patients,
            "final_bed_occupancy": self.hospital.bed_occupancy,
            "final_lab_queue": self.hospital.lab_queue,
            "final_ct_queue": self.hospital.ct_queue,
        }
