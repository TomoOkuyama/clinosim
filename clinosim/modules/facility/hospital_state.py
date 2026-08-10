"""Hospital operational state — resource utilization and staffing.

The hospital state determines how long patients wait for tests, imaging,
and procedures. Delays emerge from resource contention, not hardcoded values.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from clinosim.modules.facility._hospital_state_thresholds import (
    DELAY_CONGESTION_CAP,
    DELAY_CONGESTION_UTILIZATION_FLOOR,
    DELAY_MAX_DELAY_ROUTINE_MIN,
    DELAY_MAX_DELAY_STAT_MIN,
    DELAY_QUEUE_UTILIZATION_CEILING,
    DELAY_QUEUE_UTILIZATION_FLOOR,
    DELAY_STAFF_CAP,
    DELAY_STAFF_FLOOR,
    FALLBACK_BASE_ROUTINE_MIN,
    FALLBACK_BASE_STAT_MIN,
    FALLBACK_LAB_STAFF,
    FALLBACK_NURSING_STAFF,
    FALLBACK_OR_STAFF,
    FALLBACK_PHARMACY_STAFF,
    FALLBACK_QUEUE_UTILIZATION,
    FALLBACK_RADIOLOGY_STAFF,
    FALLBACK_REPORTING_ROUTINE_MIN,
    FALLBACK_REPORTING_STAT_MIN,
    FALLBACK_RESOURCE_CAPACITY,
    FALLBACK_WEEKEND_MODIFIER,
    SHIFT_DAY_END_HOUR_EXCLUSIVE,
    SHIFT_DAY_START_HOUR,
    SHIFT_EVENING_START_HOUR,
    WEEKEND_WEEKDAY_MIN,
)

# See clinosim/types/clinical.py for rationale (determinism chain, 2026-07-04).
_UNSET_DATETIME = datetime(1970, 1, 1)

_HERE = Path(__file__).resolve().parent
_HOSPITAL_OPERATIONS_PATH = _HERE.parents[1] / "config" / "hospital_operations.yaml"


@dataclass
class HospitalState:
    """Time-varying operational state of the hospital."""

    timestamp: datetime = field(default_factory=lambda: _UNSET_DATETIME)

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

    def update_for_time(self, dt: datetime, hospital_ops: dict[str, Any]) -> None:
        """Update staffing and baseline utilization for the given time."""
        hour = dt.hour
        weekday = dt.weekday()
        self.timestamp = dt

        # Determine shift
        staffing = hospital_ops.get("staffing", {})
        if SHIFT_DAY_START_HOUR <= hour < SHIFT_DAY_END_HOUR_EXCLUSIVE:
            shift = staffing.get("day", {})
        elif SHIFT_EVENING_START_HOUR <= hour or hour < 0:
            shift = staffing.get("evening", {})
        else:
            shift = staffing.get("night", {})

        # Apply staffing
        self.lab_staff = shift.get("lab_staff", FALLBACK_LAB_STAFF)
        self.radiology_staff = shift.get("radiology_staff", FALLBACK_RADIOLOGY_STAFF)
        self.nursing_staff = shift.get("nursing_staff", FALLBACK_NURSING_STAFF)
        self.pharmacy_staff = shift.get("pharmacy_staff", FALLBACK_PHARMACY_STAFF)
        self.or_staff = shift.get("or_staff", FALLBACK_OR_STAFF)

        # Weekend modifier
        if weekday >= WEEKEND_WEEKDAY_MIN:
            modifier = staffing.get("weekend_modifier", FALLBACK_WEEKEND_MODIFIER)
            self.lab_staff *= modifier
            self.radiology_staff *= modifier
            self.pharmacy_staff *= modifier
            self.or_staff *= modifier

        # Daily patterns
        for pattern in hospital_ops.get("daily_patterns", {}).values():
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
            for key in ["lab_queue", "ct_queue", "mri_queue", "xray_queue", "bed_occupancy", "ed_crowding"]:
                delta_key = f"{key}_delta"
                if delta_key in pattern:
                    current = getattr(self, key)
                    setattr(
                        self,
                        key,
                        min(
                            DELAY_QUEUE_UTILIZATION_CEILING,
                            max(DELAY_QUEUE_UTILIZATION_FLOOR, current + pattern[delta_key]),
                        ),
                    )

    def calculate_delay(
        self,
        resource: str,
        urgency: str,
        hospital_ops: dict[str, Any],
    ) -> float:
        """Calculate delay in minutes based on current hospital state.

        Uses queueing theory: delay = base_time / (1 - utilization) * (1 / staff)
        """
        base_times = hospital_ops.get("base_processing_time", {})
        report_times = hospital_ops.get("reporting_time", {})

        # Base processing time
        if urgency == "stat":
            base = float(base_times.get(f"{resource}_stat", base_times.get(resource, FALLBACK_BASE_STAT_MIN)))
        else:
            base = float(base_times.get(f"{resource}_routine", base_times.get(resource, FALLBACK_BASE_ROUTINE_MIN)))

        # Queue utilization
        queue_attr = f"{resource}_queue"
        if resource in ("ct", "mri", "xray", "ultrasound"):
            queue_attr = f"{resource}_queue"
        elif resource == "lab":
            queue_attr = "lab_queue"
        elif resource == "or":
            queue_attr = "or_queue"

        utilization = getattr(self, queue_attr, FALLBACK_QUEUE_UTILIZATION)
        utilization = min(DELAY_QUEUE_UTILIZATION_CEILING, max(DELAY_QUEUE_UTILIZATION_FLOOR, utilization))

        # Queueing theory: M/M/1 delay factor
        congestion_factor = 1.0 / max(DELAY_CONGESTION_UTILIZATION_FLOOR, 1.0 - utilization)

        # Staff factor
        if resource in ("ct", "mri", "xray", "ultrasound"):
            staff = self.radiology_staff
        elif resource == "lab":
            staff = self.lab_staff
        elif resource == "or":
            staff = self.or_staff
        else:
            staff = 1.0
        staff_factor = 1.0 / max(DELAY_STAFF_FLOOR, staff)

        # Cap factors to avoid pathological multiplication
        # When congestion + staff factors compound, delays can blow up
        congestion_factor = min(congestion_factor, DELAY_CONGESTION_CAP)
        staff_factor = min(staff_factor, DELAY_STAFF_CAP)

        # Reporting time (for imaging)
        reporting = 0.0
        if resource in ("ct", "mri", "xray", "ultrasound"):
            if urgency == "stat":
                reporting = float(report_times.get("stat", FALLBACK_REPORTING_STAT_MIN))
            else:
                reporting = float(report_times.get("routine", FALLBACK_REPORTING_ROUTINE_MIN))
            reporting *= staff_factor  # less staff → slower reporting

        delay = base * congestion_factor * staff_factor + reporting

        # Hard cap: stat results within 4h, routine within 12h
        max_delay = DELAY_MAX_DELAY_STAT_MIN if urgency == "stat" else DELAY_MAX_DELAY_ROUTINE_MIN
        return min(delay, max_delay)

    def add_to_queue(self, resource: str, hospital_ops: dict[str, Any]) -> None:
        """Record that a resource is being used (increases utilization)."""
        capacity = hospital_ops.get("resource_capacity", {})
        cap_map = {
            "lab": "lab_analyzers",
            "ct": "ct_scanners",
            "mri": "mri_scanners",
            "xray": "xray_rooms",
            "ultrasound": "ultrasound_rooms",
            "or": "operating_rooms",
        }
        cap_key = cap_map.get(resource, resource)
        cap = capacity.get(cap_key, FALLBACK_RESOURCE_CAPACITY)
        queue_attr = f"{resource}_queue"
        if hasattr(self, queue_attr):
            current = getattr(self, queue_attr)
            setattr(self, queue_attr, min(DELAY_QUEUE_UTILIZATION_CEILING, current + 1.0 / cap))

    def release_from_queue(self, resource: str, hospital_ops: dict[str, Any]) -> None:
        """Record that a resource is freed."""
        capacity = hospital_ops.get("resource_capacity", {})
        cap_map = {
            "lab": "lab_analyzers",
            "ct": "ct_scanners",
            "mri": "mri_scanners",
            "xray": "xray_rooms",
            "ultrasound": "ultrasound_rooms",
            "or": "operating_rooms",
        }
        cap_key = cap_map.get(resource, resource)
        cap = capacity.get(cap_key, FALLBACK_RESOURCE_CAPACITY)
        queue_attr = f"{resource}_queue"
        if hasattr(self, queue_attr):
            current = getattr(self, queue_attr)
            setattr(self, queue_attr, max(DELAY_QUEUE_UTILIZATION_FLOOR, current - 1.0 / cap))


@lru_cache(maxsize=1)
def load_hospital_operations() -> dict[str, Any]:
    """Load the default hospital operations config.

    Cached: the returned dict is a shared read-only instance — callers must not
    mutate it. (The custom ``--hospital-config PATH`` path in ``engine.py`` loads
    a fresh dict directly and is unaffected by this cache.)
    """
    if _HOSPITAL_OPERATIONS_PATH.exists():
        with open(_HOSPITAL_OPERATIONS_PATH) as f:
            return yaml.safe_load(f) or {}
    return {}
