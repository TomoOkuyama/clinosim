"""Hospital operational state — resource utilization and staffing.

The hospital state determines how long patients wait for tests, imaging,
and procedures. Delays emerge from resource contention, not hardcoded values.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml


@dataclass
class HospitalState:
    """Time-varying operational state of the hospital."""

    timestamp: datetime = field(default_factory=datetime.now)

    # Resource queue utilization (0.0=idle, 1.0=fully occupied)
    lab_queue: float = 0.1
    ct_queue: float = 0.1
    mri_queue: float = 0.1
    xray_queue: float = 0.05
    ultrasound_queue: float = 0.05
    or_queue: float = 0.1

    # Occupancy
    bed_occupancy: float = 0.7
    ed_crowding: float = 0.3

    # Staff levels (fraction of full capacity, set by shift)
    lab_staff: float = 1.0
    radiology_staff: float = 1.0
    nursing_staff: float = 1.0
    pharmacy_staff: float = 1.0
    or_staff: float = 1.0

    def update_for_time(self, dt: datetime, ops_config: dict[str, Any]) -> None:
        """Update staffing and baseline utilization for the given time."""
        hour = dt.hour
        weekday = dt.weekday()
        self.timestamp = dt

        # Determine shift
        staffing = ops_config.get("staffing", {})
        if 8 <= hour < 16:
            shift = staffing.get("day", {})
        elif 16 <= hour or hour < 0:
            shift = staffing.get("evening", {})
        else:
            shift = staffing.get("night", {})

        # Apply staffing
        self.lab_staff = shift.get("lab_staff", 0.5)
        self.radiology_staff = shift.get("radiology_staff", 0.5)
        self.nursing_staff = shift.get("nursing_staff", 0.5)
        self.pharmacy_staff = shift.get("pharmacy_staff", 0.0)
        self.or_staff = shift.get("or_staff", 0.1)

        # Weekend modifier
        if weekday >= 5:
            modifier = staffing.get("weekend_modifier", 0.6)
            self.lab_staff *= modifier
            self.radiology_staff *= modifier
            self.pharmacy_staff *= modifier
            self.or_staff *= modifier

        # Daily patterns
        for pattern in ops_config.get("daily_patterns", {}).values():
            if not isinstance(pattern, dict):
                continue
            # Check if pattern applies to this hour
            pattern_hours = pattern.get("hours")
            if pattern_hours:
                start_h, end_h = pattern_hours
                if end_h > start_h:
                    if not (start_h <= hour < end_h):
                        continue
                else:  # wraps midnight
                    if not (hour >= start_h or hour < end_h):
                        continue
            # Check weekday
            pattern_weekday = pattern.get("weekday")
            if pattern_weekday is not None and weekday != pattern_weekday:
                continue
            # Apply deltas
            for key in ["lab_queue", "ct_queue", "mri_queue", "xray_queue",
                        "bed_occupancy", "ed_crowding"]:
                delta_key = f"{key}_delta"
                if delta_key in pattern:
                    current = getattr(self, key)
                    setattr(self, key, min(0.95, max(0.0, current + pattern[delta_key])))

    def calculate_delay(
        self, resource: str, urgency: str, ops_config: dict[str, Any],
    ) -> float:
        """Calculate delay in minutes based on current hospital state.

        Uses queueing theory: delay = base_time / (1 - utilization) * (1 / staff)
        """
        base_times = ops_config.get("base_processing_time", {})
        report_times = ops_config.get("reporting_time", {})

        # Base processing time
        if urgency == "stat":
            base = float(base_times.get(f"{resource}_stat", base_times.get(resource, 20)))
        else:
            base = float(base_times.get(f"{resource}_routine", base_times.get(resource, 45)))

        # Queue utilization
        queue_attr = f"{resource}_queue"
        if resource in ("ct", "mri", "xray", "ultrasound"):
            queue_attr = f"{resource}_queue"
        elif resource == "lab":
            queue_attr = "lab_queue"
        elif resource == "or":
            queue_attr = "or_queue"

        utilization = getattr(self, queue_attr, 0.1)
        utilization = min(0.95, max(0.0, utilization))

        # Queueing theory: M/M/1 delay factor
        congestion_factor = 1.0 / max(0.05, 1.0 - utilization)

        # Staff factor
        if resource in ("ct", "mri", "xray", "ultrasound"):
            staff = self.radiology_staff
        elif resource == "lab":
            staff = self.lab_staff
        elif resource == "or":
            staff = self.or_staff
        else:
            staff = 1.0
        staff_factor = 1.0 / max(0.1, staff)

        # Cap factors to avoid pathological multiplication
        # When congestion + staff factors compound, delays can blow up
        congestion_factor = min(congestion_factor, 5.0)  # max 5x slowdown from congestion
        staff_factor = min(staff_factor, 4.0)  # max 4x slowdown from staffing (matches night-shift reality)

        # Reporting time (for imaging)
        reporting = 0.0
        if resource in ("ct", "mri", "xray", "ultrasound"):
            if urgency == "stat":
                reporting = float(report_times.get("stat", 15))
            else:
                reporting = float(report_times.get("routine", 120))
            reporting *= staff_factor  # less staff → slower reporting

        delay = base * congestion_factor * staff_factor + reporting

        # Hard cap: stat results within 4h, routine within 12h
        max_delay = 240.0 if urgency == "stat" else 720.0  # minutes
        return min(delay, max_delay)

    def add_to_queue(self, resource: str, ops_config: dict[str, Any]) -> None:
        """Record that a resource is being used (increases utilization)."""
        capacity = ops_config.get("resource_capacity", {})
        cap_map = {
            "lab": "lab_analyzers", "ct": "ct_scanners", "mri": "mri_scanners",
            "xray": "xray_rooms", "ultrasound": "ultrasound_rooms", "or": "operating_rooms",
        }
        cap_key = cap_map.get(resource, resource)
        cap = capacity.get(cap_key, 5)
        queue_attr = f"{resource}_queue"
        if hasattr(self, queue_attr):
            current = getattr(self, queue_attr)
            setattr(self, queue_attr, min(0.95, current + 1.0 / cap))

    def release_from_queue(self, resource: str, ops_config: dict[str, Any]) -> None:
        """Record that a resource is freed."""
        capacity = ops_config.get("resource_capacity", {})
        cap_map = {
            "lab": "lab_analyzers", "ct": "ct_scanners", "mri": "mri_scanners",
            "xray": "xray_rooms", "ultrasound": "ultrasound_rooms", "or": "operating_rooms",
        }
        cap_key = cap_map.get(resource, resource)
        cap = capacity.get(cap_key, 5)
        queue_attr = f"{resource}_queue"
        if hasattr(self, queue_attr):
            current = getattr(self, queue_attr)
            setattr(self, queue_attr, max(0.0, current - 1.0 / cap))


def load_hospital_operations() -> dict[str, Any]:
    """Load hospital operations config."""
    config_path = Path(__file__).parent.parent.parent / "config" / "hospital_operations.yaml"
    if config_path.exists():
        with open(config_path) as f:
            return yaml.safe_load(f) or {}
    return {}
