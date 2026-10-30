"""Hospital operational state — resource utilization and staffing.

The hospital state determines how long patients wait for tests, imaging,
and procedures. Delays emerge from resource contention, not hardcoded values.
"""

from __future__ import annotations

import heapq
from dataclasses import dataclass, field
from datetime import datetime, timedelta
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

# Queue attributes, keyed by resource. Their value is recomputed from the
# baseline, the work in progress and the active daily patterns (Issue #2196).
_QUEUE_ATTRS = {
    "lab": "lab_queue",
    "ct": "ct_queue",
    "mri": "mri_queue",
    "xray": "xray_queue",
    "ultrasound": "ultrasound_queue",
    "or": "or_queue",
}
_CAPACITY_KEYS = {
    "lab": "lab_analyzers",
    "ct": "ct_scanners",
    "mri": "mri_scanners",
    "xray": "xray_rooms",
    "ultrasound": "ultrasound_rooms",
    "or": "operating_rooms",
}

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

    # Issue #2196: work in progress per resource (utilisation units) and the
    # completion times at which it is released. Queue attributes used to only
    # grow (nothing released them) and daily-pattern deltas were added again
    # on every update, so long runs saturated every queue at the ceiling.
    _baseline: dict[str, float] = field(default_factory=dict, repr=False)
    _occupancy: dict[str, float] = field(default_factory=dict, repr=False)
    _pending: list[tuple[datetime, int, str, float]] = field(default_factory=list, repr=False)
    _pattern_delta: dict[str, float] = field(default_factory=dict, repr=False)
    # Pattern deltas currently applied to the externally managed occupancy
    # levels (bed_occupancy, ed_crowding); swapped, not stacked, on update.
    _applied_level_delta: dict[str, float] = field(default_factory=dict, repr=False)
    _seq: int = field(default=0, repr=False)

    def __post_init__(self) -> None:
        self._baseline = {res: getattr(self, attr) for res, attr in _QUEUE_ATTRS.items()}

    def _refresh_queue(self, resource: str) -> None:
        value = (
            self._baseline.get(resource, 0.0)
            + self._occupancy.get(resource, 0.0)
            + self._pattern_delta.get(resource, 0.0)
        )
        setattr(
            self,
            _QUEUE_ATTRS[resource],
            min(DELAY_QUEUE_UTILIZATION_CEILING, max(DELAY_QUEUE_UTILIZATION_FLOOR, value)),
        )

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

        # Release work whose completion time has passed.
        while self._pending and self._pending[0][0] <= dt:
            _, _, res, units = heapq.heappop(self._pending)
            self._occupancy[res] = max(0.0, self._occupancy.get(res, 0.0) - units)

        # Daily patterns apply while active; they are recomputed on every
        # update instead of being added on top of the previous value.
        self._pattern_delta = {}
        level_delta: dict[str, float] = {}
        for pattern in hospital_ops.get("daily_patterns", {}).values():
            if not isinstance(pattern, dict) or not self._pattern_active(pattern, hour, weekday):
                continue
            for res, attr in _QUEUE_ATTRS.items():
                delta = pattern.get(f"{attr}_delta")
                if delta is not None:
                    self._pattern_delta[res] = self._pattern_delta.get(res, 0.0) + float(delta)
            for key in ("bed_occupancy", "ed_crowding"):
                if f"{key}_delta" in pattern:
                    level_delta[key] = level_delta.get(key, 0.0) + float(pattern[f"{key}_delta"])
        for key in ("bed_occupancy", "ed_crowding"):
            value = getattr(self, key) - self._applied_level_delta.get(key, 0.0) + level_delta.get(key, 0.0)
            setattr(self, key, value)
        self._applied_level_delta = level_delta
        for res in _QUEUE_ATTRS:
            self._refresh_queue(res)

    @staticmethod
    def _pattern_active(pattern: dict, hour: int, weekday: int) -> bool:
        pattern_hours = pattern.get("hours")
        if pattern_hours:
            start_h, end_h = pattern_hours
            if end_h > start_h:
                if not (start_h <= hour < end_h):
                    return False
            elif not (hour >= start_h or hour < end_h):
                return False
        pattern_weekday = pattern.get("weekday")
        return pattern_weekday is None or weekday == pattern_weekday

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

    def add_to_queue(
        self,
        resource: str,
        hospital_ops: dict[str, Any],
        until: datetime | None = None,
    ) -> None:
        """Record that a resource is busy until ``until`` (raises utilisation).

        Without ``until`` the work holds the resource for its routine base
        processing time from the current state timestamp. The utilisation is
        released when ``update_for_time`` passes the completion time.
        """
        if resource not in _QUEUE_ATTRS:
            return
        cap = hospital_ops.get("resource_capacity", {}).get(_CAPACITY_KEYS[resource], FALLBACK_RESOURCE_CAPACITY)
        units = 1.0 / cap
        self._occupancy[resource] = self._occupancy.get(resource, 0.0) + units
        if until is None:
            base = hospital_ops.get("base_processing_time", {})
            minutes = float(base.get(f"{resource}_routine", base.get(resource, FALLBACK_BASE_ROUTINE_MIN)))
            until = self.timestamp + timedelta(minutes=minutes)
        self._seq += 1
        heapq.heappush(self._pending, (until, self._seq, resource, units))
        self._refresh_queue(resource)

    def release_from_queue(self, resource: str, hospital_ops: dict[str, Any]) -> None:
        """Release one unit of work on ``resource`` immediately."""
        if resource not in _QUEUE_ATTRS:
            return
        cap = hospital_ops.get("resource_capacity", {}).get(_CAPACITY_KEYS[resource], FALLBACK_RESOURCE_CAPACITY)
        self._occupancy[resource] = max(0.0, self._occupancy.get(resource, 0.0) - 1.0 / cap)
        self._refresh_queue(resource)


@lru_cache(maxsize=1)
def load_hospital_operations() -> dict[str, Any]:
    """Load the default hospital operations config.

    Cached: the returned dict is a shared read-only instance — callers must not
    mutate it. (The custom ``--hospital-config PATH`` path in ``engine.py`` loads
    a fresh dict directly and is unaffected by this cache.)
    """
    if _HOSPITAL_OPERATIONS_PATH.exists():
        with open(_HOSPITAL_OPERATIONS_PATH, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {}
