"""Hospital-state / queueing-delay thresholds (Issue #637).

``clinosim/modules/facility/hospital_state.py`` models the hospital
operational state — shift-based staffing, resource-queue utilization,
and M/M/1-style delay calculation. Every scalar the module carried
inline is lifted here per policy §5.

The module owns two clusters of magic numbers:

1. **Shift and schedule** — day / evening / night boundary hours,
   weekend detection, weekend staffing fallback.
2. **Queueing / delay** — utilization clamps, congestion / staff cap
   safeguards against pathological blow-up, hard delay ceilings, and
   YAML fallback values (base processing time, reporting time,
   resource capacity).

Byte-diff verification: hospital-state math is deterministic (no
RNG). Byte-identity at the pinned seed is guaranteed as long as
arithmetic order is preserved, which the constant substitution does
exactly.
"""

from __future__ import annotations

__all__ = [
    "DELAY_MAX_DELAY_ROUTINE_MIN",
    "DELAY_MAX_DELAY_STAT_MIN",
    "DELAY_CONGESTION_CAP",
    "DELAY_CONGESTION_UTILIZATION_FLOOR",
    "DELAY_QUEUE_UTILIZATION_CEILING",
    "DELAY_QUEUE_UTILIZATION_FLOOR",
    "DELAY_STAFF_CAP",
    "DELAY_STAFF_FLOOR",
    "FALLBACK_BASE_ROUTINE_MIN",
    "FALLBACK_BASE_STAT_MIN",
    "FALLBACK_LAB_STAFF",
    "FALLBACK_NURSING_STAFF",
    "FALLBACK_OR_STAFF",
    "FALLBACK_PHARMACY_STAFF",
    "FALLBACK_QUEUE_UTILIZATION",
    "FALLBACK_RADIOLOGY_STAFF",
    "FALLBACK_REPORTING_ROUTINE_MIN",
    "FALLBACK_REPORTING_STAT_MIN",
    "FALLBACK_RESOURCE_CAPACITY",
    "FALLBACK_WEEKEND_MODIFIER",
    "SHIFT_DAY_END_HOUR_EXCLUSIVE",
    "SHIFT_DAY_START_HOUR",
    "SHIFT_EVENING_START_HOUR",
    "WEEKEND_WEEKDAY_MIN",
]


# ---------------------------------------------------------------------------
# Shift boundaries (0-23 hour convention)
# ---------------------------------------------------------------------------

SHIFT_DAY_START_HOUR: int = 8
"""Hour (inclusive) at which the day shift starts.

08:00 matches the standard hospital day-shift start across US and JP."""

SHIFT_DAY_END_HOUR_EXCLUSIVE: int = 16
"""Hour (exclusive) at which the day shift ends and the evening
shift begins.

16:00 = 4 PM matches standard 8-hour day-shift convention."""

SHIFT_EVENING_START_HOUR: int = 16
"""Hour at or above which the evening shift begins (matches
:data:`SHIFT_DAY_END_HOUR_EXCLUSIVE`).

Kept as a separate named constant because the evening-shift check
uses ``hour >= SHIFT_EVENING_START_HOUR`` while the day-shift check
uses ``hour < SHIFT_DAY_END_HOUR_EXCLUSIVE`` — same numeric value,
distinct semantic role."""

WEEKEND_WEEKDAY_MIN: int = 5
"""Minimum ``weekday()`` value that flags a weekend day.

``datetime.weekday()`` returns 0=Monday .. 6=Sunday; 5 = Saturday
and 6 = Sunday are the weekend."""


# ---------------------------------------------------------------------------
# YAML-fallback staffing values (used when hospital_operations.yaml
# does not provide shift-specific staff levels)
# ---------------------------------------------------------------------------

FALLBACK_LAB_STAFF: float = 0.5
"""Fallback lab-staff level (0-1 fraction of full capacity) when the
shift's ``lab_staff`` entry is missing.

Empirical tuning for the synthetic simulator: 0.5 = half-capacity is
a reasonable off-hours fallback that keeps the M/M/1 delay finite."""

FALLBACK_RADIOLOGY_STAFF: float = 0.5
"""Fallback radiology-staff level."""

FALLBACK_NURSING_STAFF: float = 0.5
"""Fallback nursing-staff level."""

FALLBACK_PHARMACY_STAFF: float = 0.0
"""Fallback pharmacy-staff level.

0.0 (closed) matches the observation that pharmacy departments
typically have night-shift skeleton crews or on-call only; the
:data:`DELAY_STAFF_FLOOR` prevents division-by-zero downstream."""

FALLBACK_OR_STAFF: float = 0.1
"""Fallback OR-staff level.

0.1 (10% capacity) matches on-call OR staffing for emergency-only
overnight coverage."""

FALLBACK_WEEKEND_MODIFIER: float = 0.6
"""Fallback weekend staffing modifier applied when the YAML's
``weekend_modifier`` is missing.

Empirical tuning for the synthetic simulator: 60% weekend staffing
reflects the observed reduction from the weekday baseline (typical
JP / US hospital lab / radiology / pharmacy / OR staffing all drop
to roughly 60-70% on weekends)."""


# ---------------------------------------------------------------------------
# Queue-utilization clamp
# ---------------------------------------------------------------------------

DELAY_QUEUE_UTILIZATION_FLOOR: float = 0.0
"""Minimum queue utilization — a resource cannot be less than idle."""

DELAY_QUEUE_UTILIZATION_CEILING: float = 0.95
"""Maximum queue utilization — capped just below 1.0 to prevent
division-by-zero blow-up in the M/M/1 congestion formula
``1 / (1 - utilization)``.

Empirical tuning for the synthetic simulator: 0.95 caps the maximum
congestion multiplier at 20× (before the further
:data:`DELAY_CONGESTION_CAP` cap)."""

FALLBACK_QUEUE_UTILIZATION: float = 0.1
"""Fallback queue-utilization value when the resource's queue
attribute is missing.

Matches the class-default queue utilization for a lightly-used
resource."""


# ---------------------------------------------------------------------------
# Delay formula caps + fallback base / reporting times
# ---------------------------------------------------------------------------

DELAY_CONGESTION_UTILIZATION_FLOOR: float = 0.05
"""Minimum denominator in the M/M/1 congestion formula
``1 / max(0.05, 1 - utilization)``.

Empirical tuning for the synthetic simulator: caps the congestion
factor at 1/0.05 = 20× before the further
:data:`DELAY_CONGESTION_CAP` cap."""

DELAY_STAFF_FLOOR: float = 0.1
"""Minimum denominator in the staff factor
``1 / max(0.1, staff)``.

Empirical tuning for the synthetic simulator: caps the staff-factor
at 1/0.1 = 10× — prevents division-by-zero when
:data:`FALLBACK_PHARMACY_STAFF` (0.0) is in effect."""

DELAY_CONGESTION_CAP: float = 5.0
"""Hard cap on the congestion factor applied after the M/M/1 formula.

Empirical tuning for the synthetic simulator: 5× is the maximum
plausible slowdown from queue congestion alone — beyond this, real
hospitals would open additional capacity or defer non-urgent work."""

DELAY_STAFF_CAP: float = 4.0
"""Hard cap on the staff factor applied after the ``1 / staff``
inverse.

Empirical tuning for the synthetic simulator: 4× matches the observed
night-shift reality — even skeleton crews rarely produce more than
a 4× slowdown compared to full weekday staffing."""

DELAY_MAX_DELAY_STAT_MIN: float = 240.0
"""Hard delay ceiling for STAT orders (minutes) — 4 hours.

Empirical tuning for the synthetic simulator: STAT orders that
would otherwise exceed 4 hours are capped, matching the clinical
convention that a STAT order sitting past 4 hours would be re-
prioritized / expedited manually."""

DELAY_MAX_DELAY_ROUTINE_MIN: float = 720.0
"""Hard delay ceiling for routine orders (minutes) — 12 hours.

Empirical tuning for the synthetic simulator: routine orders that
would exceed 12 hours are capped, matching the convention that
same-day routine turnaround is the outer clinical expectation."""

FALLBACK_BASE_STAT_MIN: int = 20
"""Fallback base processing time (minutes) for STAT orders when the
YAML entry is missing."""

FALLBACK_BASE_ROUTINE_MIN: int = 45
"""Fallback base processing time (minutes) for routine orders."""

FALLBACK_REPORTING_STAT_MIN: int = 15
"""Fallback reporting time (minutes) for STAT imaging reads."""

FALLBACK_REPORTING_ROUTINE_MIN: int = 120
"""Fallback reporting time (minutes) for routine imaging reads —
2 hours matches the routine core-radiology turnaround."""


# ---------------------------------------------------------------------------
# Resource capacity fallback
# ---------------------------------------------------------------------------

FALLBACK_RESOURCE_CAPACITY: int = 5
"""Fallback resource-count when the YAML's ``resource_capacity``
does not name the resource.

Empirical tuning for the synthetic simulator: 5 units is a
reasonable mid-sized-hospital default (mid-range for lab analyzers /
CT scanners / imaging rooms) — each queue add increments utilization
by 1/5 = 20%."""
