"""Imaging-result turnaround-time distributions (Issue #637 sibling).

The ``calculate_imaging_result_time`` function in
``modules/order/engine.py`` models real-world imaging TAT — a
combination of a scheduling delay (order → exam start) and a reporting
delay (exam → radiologist report). Both depend on modality (X-ray /
CT / MRI / Echo·US) and on the STAT-vs-routine urgency flag; weekends
and nights add extra delay.

Every scalar the function used inline is lifted here per policy §5,
grouped into five families for readability:

1. **STAT scheduling delays** — quick-turnaround exam start for
   emergency workups.
2. **Routine scheduling delays** — modality-specific waits for
   scheduled exams (MRI queues are days, X-rays are hours).
3. **Weekend and MRI-defer modifiers** — reduced-staffing multiplier
   plus the special-case Monday defer for routine MRI ordered on a
   weekend.
4. **Night-shift deferral** — routine orders placed at night are
   pushed to the morning imaging batch (6 AM target).
5. **Reporting delays** — radiologist read + write TAT, STAT vs
   routine.

Byte-diff verification: swapping the inline literals for these named
constants MUST NOT change any RNG-consuming call. ``rng.normal(mean,
std)`` produces bit-identical draws whether the arguments come from
literals or module-scope floats.
"""

from __future__ import annotations

__all__ = [
    "IMAGING_MIN_TOTAL_DELAY_MIN",
    "IMAGING_NIGHT_HOUR_END",
    "IMAGING_NIGHT_HOUR_START",
    "IMAGING_NIGHT_MORNING_TARGET_HOUR",
    "IMAGING_WEEKEND_MRI_MONDAY_DEFER_MIN",
    "IMAGING_WEEKEND_MULTIPLIER",
    "ROUTINE_CT_SCHEDULE_MEAN_MIN",
    "ROUTINE_CT_SCHEDULE_STD_MIN",
    "ROUTINE_ECHO_US_SCHEDULE_MEAN_MIN",
    "ROUTINE_ECHO_US_SCHEDULE_STD_MIN",
    "ROUTINE_MRI_SCHEDULE_MEAN_MIN",
    "ROUTINE_MRI_SCHEDULE_STD_MIN",
    "ROUTINE_REPORT_MEAN_MIN",
    "ROUTINE_REPORT_STD_MIN",
    "ROUTINE_XRAY_SCHEDULE_MEAN_MIN",
    "ROUTINE_XRAY_SCHEDULE_STD_MIN",
    "STAT_CT_MRI_SCHEDULE_MEAN_MIN",
    "STAT_CT_MRI_SCHEDULE_STD_MIN",
    "STAT_REPORT_MEAN_MIN",
    "STAT_REPORT_STD_MIN",
    "STAT_XRAY_SCHEDULE_MEAN_MIN",
    "STAT_XRAY_SCHEDULE_STD_MIN",
]


# ---------------------------------------------------------------------------
# Family 1: STAT scheduling delays (order → exam start)
# ---------------------------------------------------------------------------

STAT_CT_MRI_SCHEDULE_MEAN_MIN: float = 60.0
"""Mean scheduling delay (minutes) for a STAT CT or MRI. ~1 h reflects
the typical STAT CT workflow (patient transport + scanner queue) at a
tertiary-care hospital; STAT MRI is faster in principle but shares
the same STAT-priority queue for modeling simplicity."""

STAT_CT_MRI_SCHEDULE_STD_MIN: float = 20.0
"""Standard deviation of the STAT CT / MRI scheduling delay."""

STAT_XRAY_SCHEDULE_MEAN_MIN: float = 30.0
"""Mean scheduling delay (minutes) for a STAT plain film / X-ray.
Portable X-ray in a monitored bed or an ED bay resolves faster than
scanner exams because the equipment comes to the patient."""

STAT_XRAY_SCHEDULE_STD_MIN: float = 10.0
"""Standard deviation of the STAT X-ray scheduling delay."""


# ---------------------------------------------------------------------------
# Family 2: routine scheduling delays (order → exam start)
# ---------------------------------------------------------------------------

ROUTINE_MRI_SCHEDULE_MEAN_MIN: float = 24 * 60.0
"""Mean scheduling delay (minutes) for a routine MRI — 24 h (1 day).
MRI scanner-time is the scarcest imaging resource at most hospitals;
routine outpatient MRI slots regularly book 1-2 days out."""

ROUTINE_MRI_SCHEDULE_STD_MIN: float = 8 * 60.0
"""Standard deviation of the routine MRI scheduling delay — 8 h. Wide
spread reflects the day-of-week and time-of-day variability in MRI
slot availability."""

ROUTINE_CT_SCHEDULE_MEAN_MIN: float = 4 * 60.0
"""Mean scheduling delay (minutes) for a routine CT — 4 h. CT has
higher throughput than MRI and can be batch-scanned; routine CT
typically resolves the same day."""

ROUTINE_CT_SCHEDULE_STD_MIN: float = 2 * 60.0
"""Standard deviation of the routine CT scheduling delay — 2 h."""

ROUTINE_ECHO_US_SCHEDULE_MEAN_MIN: float = 3 * 60.0
"""Mean scheduling delay (minutes) for a routine echocardiogram or
ultrasound — 3 h. Ultrasound is portable and cardiac sonographers
usually maintain a same-day queue."""

ROUTINE_ECHO_US_SCHEDULE_STD_MIN: float = 60.0
"""Standard deviation of the routine echo / ultrasound scheduling
delay — 1 h."""

ROUTINE_XRAY_SCHEDULE_MEAN_MIN: float = 60.0
"""Mean scheduling delay (minutes) for a routine X-ray — 1 h."""

ROUTINE_XRAY_SCHEDULE_STD_MIN: float = 30.0
"""Standard deviation of the routine X-ray scheduling delay."""


# ---------------------------------------------------------------------------
# Family 3: weekend and MRI-defer modifiers
# ---------------------------------------------------------------------------

IMAGING_WEEKEND_MULTIPLIER: float = 1.5
"""Multiplier applied to the scheduling delay on weekends (Sat / Sun).
Reflects reduced radiology staffing — every modality's queue moves
~50 % slower on non-weekdays."""

IMAGING_WEEKEND_MRI_MONDAY_DEFER_MIN: float = 24 * 60.0
"""Extra minutes added to routine (non-STAT) MRI scheduling delay
when the order is placed on a weekend. Most non-STAT MRI slots are
weekday-only, so a Saturday order effectively defers to Monday —
this constant approximates the extra 1-day wait beyond the base
weekend multiplier."""


# ---------------------------------------------------------------------------
# Family 4: night-shift deferral (mirrors _lab_result_timing.py)
# ---------------------------------------------------------------------------

IMAGING_NIGHT_HOUR_START: int = 22
"""Hour (24-hour clock) at which the imaging "night" period begins.
Routine orders placed at or after this hour are queued for the
morning imaging batch."""

IMAGING_NIGHT_HOUR_END: int = 6
"""Hour (24-hour clock, exclusive) at which the imaging "night" period
ends. Routine orders placed before this hour are still queued for the
morning batch (the day shift hasn't started yet)."""

IMAGING_NIGHT_MORNING_TARGET_HOUR: int = 6
"""Target hour at which the deferred night order's exam actually
starts. The deferral arithmetic in ``calculate_imaging_result_time``
computes minutes-until-target as ``(TARGET - hour) * 60`` for
after-midnight (hour < NIGHT_HOUR_END) or ``((TARGET + 24) - hour)
* 60`` for pre-midnight (hour >= NIGHT_HOUR_START) — both resolve to
the next 6 AM."""


# ---------------------------------------------------------------------------
# Family 5: reporting delays (exam done → radiologist report available)
# ---------------------------------------------------------------------------

STAT_REPORT_MEAN_MIN: float = 30.0
"""Mean radiologist reporting delay (minutes) for a STAT read. Real
STAT reads at trauma / stroke / PE-workup priorities land in the
20-40 min band."""

STAT_REPORT_STD_MIN: float = 10.0
"""Standard deviation of the STAT reporting delay."""

ROUTINE_REPORT_MEAN_MIN: float = 4 * 60.0
"""Mean radiologist reporting delay (minutes) for a routine read —
4 h. Routine reads batch through a radiologist's daily worklist;
same-day turnaround is the target with a 2-6 h band."""

ROUTINE_REPORT_STD_MIN: float = 2 * 60.0
"""Standard deviation of the routine reporting delay."""


# ---------------------------------------------------------------------------
# Minimum floor
# ---------------------------------------------------------------------------

IMAGING_MIN_TOTAL_DELAY_MIN: int = 15
"""Minimum total imaging delay (minutes) after schedule + report + all
modifiers. 15 min is the physical lower bound of order-to-result
even in the fastest STAT X-ray + immediate read case."""
