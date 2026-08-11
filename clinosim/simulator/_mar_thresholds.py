"""Medication-Administration Record (MAR) generation thresholds (Issue #637).

Lifts the previously-inline scalars from
:func:`clinosim.simulator.medication_pipeline._generate_mar` and its
STAT ad-hoc dose pre-scheduling per policy §5.

Every scalar here fires deterministically off the master RNG
(``rng.integers``, ``rng.random``, ``rng.normal``), so byte-identity
of golden cohorts is the required acceptance for the extraction.
"""

from __future__ import annotations

__all__ = [
    "MAR_ANTIHYPERTENSIVE_HOLD_SBP_THRESHOLD",
    "MAR_JITTER_MEAN_MIN",
    "MAR_JITTER_STD_MIN",
    "MAR_PATIENT_REFUSAL_PROBABILITY",
    "MAR_STAT_DUPLICATE_AVOIDANCE_WINDOW_SEC",
    "MAR_STAT_FIRST_DOSE_DELAY_MAX_EXCLUSIVE",
    "MAR_STAT_FIRST_DOSE_DELAY_MIN",
]


# ---------------------------------------------------------------------------
# STAT ad-hoc first-dose scheduling (sepsis abx, cardiogenic-shock pressor,
# anaphylaxis epinephrine — bypasses the scheduled q6/8h grid on Day 0)
# ---------------------------------------------------------------------------

MAR_STAT_FIRST_DOSE_DELAY_MIN: int = 30
"""Inclusive lower bound of the STAT first-dose minute-delay draw
after admission (``rng.integers``). Chosen so the empirical-response
window for the Surviving Sepsis 3h antibiotic bundle target is met —
30-60 min from admission puts the first dose comfortably inside the
bundle window."""

MAR_STAT_FIRST_DOSE_DELAY_MAX_EXCLUSIVE: int = 61
"""Exclusive upper bound of the STAT first-dose delay draw. Combined
with :data:`MAR_STAT_FIRST_DOSE_DELAY_MIN` yields 30-60 minutes."""

MAR_STAT_DUPLICATE_AVOIDANCE_WINDOW_SEC: int = 5400
"""Time window (seconds) around the STAT ad-hoc dose within which a
scheduled-grid slot is skipped to avoid double-administration.
5400 s = 90 min — half of the standard q3h medication interval,
which prevents back-to-back doses without disrupting the q6/q8/q12h
grid downstream."""


# ---------------------------------------------------------------------------
# Clinical-hold criteria
# ---------------------------------------------------------------------------

MAR_ANTIHYPERTENSIVE_HOLD_SBP_THRESHOLD: int = 90
"""SBP (mmHg) at or below which an antihypertensive dose is coded as
"held". Matches the standard clinical hold-parameter threshold —
below 90 SBP the risk of further BP lowering outweighs the
antihypertensive benefit."""


# ---------------------------------------------------------------------------
# Patient behavior + administration jitter
# ---------------------------------------------------------------------------

MAR_PATIENT_REFUSAL_PROBABILITY: float = 0.015
"""Per-dose probability that the patient refuses the medication
(status="refused"). Empirical tuning for the synthetic simulator:
1.5%/dose reflects the observed inpatient refusal rate (higher than
the ~0.5% "held" rate but lower than the ~5% dose-skip-and-
reschedule rate)."""

MAR_JITTER_MEAN_MIN: float = 5.0
"""Mean minute-offset of actual vs scheduled MAR administration time
(``rng.normal``). +5 min mean captures the typical "few minutes late"
nurse-administered dose pattern."""

MAR_JITTER_STD_MIN: float = 10.0
"""Standard deviation of the actual-vs-scheduled administration time
jitter. 10 min σ keeps most doses within ±20 min of scheduled while
allowing occasional larger deviations (rounding delays, patient off
the ward for imaging, etc.)."""
