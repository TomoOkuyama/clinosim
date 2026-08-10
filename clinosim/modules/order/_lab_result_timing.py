"""Lab-result turnaround-time distributions (Issue #637).

The ``calculate_lab_result_time`` function in
``modules/order/engine.py`` models real-world lab-result timing —
STAT vs routine base delay, night-shift deferral to next-morning
processing, weekend slowdown, random congestion, and evening
throughput drop.

Every scalar the function used inline is lifted here per policy §5,
grouped into four families for readability:

1. **Base delay distributions** — STAT vs routine base delay before
   any time-of-day / day-of-week modifier applies.
2. **Night-shift deferral** — routine orders placed between the
   night-hour bounds are queued for the next-morning core-lab batch
   start.
3. **Weekend and evening modifiers** — multipliers on the base delay
   for reduced-staffing periods.
4. **Random congestion** — probability that a given order hits a
   batch / equipment queue and receives an exponential extra delay.

Byte-diff verification: swapping the inline literals for these named
constants MUST NOT change any RNG-consuming call. ``rng.normal`` /
``rng.random`` / ``rng.exponential`` produce bit-identical draws
whether their arguments come from literals or module-scope floats.
"""

from __future__ import annotations

__all__ = [
    "CONGESTION_EXTRA_MEAN_MIN",
    "CONGESTION_PROBABILITY",
    "EVENING_HOUR_END",
    "EVENING_HOUR_START",
    "EVENING_STAFFING_MULTIPLIER",
    "LAB_RESULT_MIN_DELAY_MIN",
    "NIGHT_HOUR_END",
    "NIGHT_HOUR_START",
    "NIGHT_MORNING_START_HOUR",
    "NIGHT_MORNING_START_MINUTE",
    "POST_NIGHT_ADDITIONAL_MEAN_MIN",
    "POST_NIGHT_ADDITIONAL_STD_MIN",
    "ROUTINE_LAB_BASE_MEAN_MIN",
    "ROUTINE_LAB_BASE_STD_MIN",
    "STAT_LAB_BASE_MEAN_MIN",
    "STAT_LAB_BASE_STD_MIN",
    "WEEKEND_NON_URGENT_ADDITIONAL_MULTIPLIER",
    "WEEKEND_STAFFING_MULTIPLIER",
]


# ---------------------------------------------------------------------------
# Family 1: base delay distributions (minutes)
# ---------------------------------------------------------------------------

STAT_LAB_BASE_MEAN_MIN: float = 45.0
"""Mean base delay (minutes) for a STAT lab result. 45 min matches the
published core-lab turnaround for STAT chemistry / hematology at an
average hospital — the "45-minute rule" quality target."""

STAT_LAB_BASE_STD_MIN: float = 15.0
"""Standard deviation of the STAT base-delay draw."""

ROUTINE_LAB_BASE_MEAN_MIN: float = 120.0
"""Mean base delay (minutes) for a routine lab result. 2 hours matches
the standard "routine chemistry" batch processing interval — the
result flows into the next available batch, so a routine order placed
mid-batch waits ~2 h on average."""

ROUTINE_LAB_BASE_STD_MIN: float = 30.0
"""Standard deviation of the routine base-delay draw."""


# ---------------------------------------------------------------------------
# Family 2: night-shift deferral
# ---------------------------------------------------------------------------

NIGHT_HOUR_START: int = 22
"""Hour (24-hour clock) at which the "night shift" begins. Routine
(non-STAT) orders placed at or after this hour are queued for the
next-morning batch."""

NIGHT_HOUR_END: int = 6
"""Hour (24-hour clock, exclusive) at which the "night shift" ends.
Routine orders placed before this hour are still queued for the
next-morning batch (the shift hasn't handed over yet)."""

NIGHT_MORNING_START_HOUR: int = 6
"""Hour at which the next-morning core-lab batch starts processing
deferred night orders."""

NIGHT_MORNING_START_MINUTE: int = 30
"""Minute of :data:`NIGHT_MORNING_START_HOUR` at which the batch
starts. 6:30 AM is the standard shift-change + first-batch time in
most hospital core labs."""

POST_NIGHT_ADDITIONAL_MEAN_MIN: float = 90.0
"""Mean additional delay (minutes) after the morning batch starts
before a deferred night order actually resolves. Captures the queue
depth from the accumulated overnight orders."""

POST_NIGHT_ADDITIONAL_STD_MIN: float = 30.0
"""Standard deviation of the post-night additional-delay draw."""


# ---------------------------------------------------------------------------
# Family 3: weekend and evening staffing modifiers
# ---------------------------------------------------------------------------

WEEKEND_STAFFING_MULTIPLIER: float = 1.5
"""Multiplier applied to the base lab-result delay on weekends (Sat /
Sun). Reflects the reduced core-lab staffing on non-weekdays — every
order takes ~50 % longer to resolve."""

WEEKEND_NON_URGENT_ADDITIONAL_MULTIPLIER: float = 1.3
"""Additional multiplier stacked on top of
:data:`WEEKEND_STAFFING_MULTIPLIER` for NON-urgent orders on weekends.
STAT orders keep the base 1.5× weekend penalty; routine orders get
1.5 × 1.3 = 1.95× because they queue behind everything else."""

EVENING_HOUR_START: int = 17
"""Hour at which "evening reduced-staff" period begins. Orders placed
between this and :data:`EVENING_HOUR_END` receive a small delay bump
(:data:`EVENING_STAFFING_MULTIPLIER`)."""

EVENING_HOUR_END: int = 22
"""Hour at which the evening reduced-staff period ends and the night
shift begins (see :data:`NIGHT_HOUR_START`)."""

EVENING_STAFFING_MULTIPLIER: float = 1.2
"""Multiplier applied to the base delay for orders placed in the
evening reduced-staff window (~20 % slower)."""


# ---------------------------------------------------------------------------
# Family 4: random congestion + minimum floor
# ---------------------------------------------------------------------------

CONGESTION_PROBABILITY: float = 0.15
"""Probability that a given lab order hits a batch / equipment
congestion event and receives an extra exponential delay."""

CONGESTION_EXTRA_MEAN_MIN: float = 30.0
"""Mean of the exponential-distribution extra delay (minutes) when the
:data:`CONGESTION_PROBABILITY` draw fires. Exponential mean 30 min
implies a long tail — 5 % of congested orders wait 90+ min extra."""

LAB_RESULT_MIN_DELAY_MIN: float = 15.0
"""Minimum lab-result delay floor (minutes) after all multipliers and
extras are applied. 15 min is the physical lower bound of specimen
handling + instrument processing — even a STAT order in a perfectly-
staffed empty core lab cannot resolve faster than this."""
