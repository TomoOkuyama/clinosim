"""Outpatient follow-up workflow thresholds (Issue #637).

The outpatient simulator in ``clinosim/simulator/outpatient.py`` shapes
each follow-up visit's timing and prescription defaults with a small
set of previously-inline scalars — lifted here per policy §5.

Compared to inpatient / ED, an outpatient follow-up is a much simpler
workflow: patient arrives → vitals in triage → provider assessment →
labs sent to core lab → prescription renewal → discharge. The
constants below capture the four timing points and the standard
prescription-duration default that shape that flow.

Byte-diff verification: swapping the inline literals for these named
constants MUST NOT change any RNG-consuming call.
``rng.integers(low, high)`` and ``timedelta(...)`` both produce
bit-identical values whether their args come from literals or
module-scope constants.
"""

from __future__ import annotations

__all__ = [
    "OUTPATIENT_LAB_ORDER_OFFSET_MIN",
    "OUTPATIENT_LAB_RESULT_OFFSET_HOURS",
    "OUTPATIENT_PRESCRIPTION_DURATION_DAYS",
    "OUTPATIENT_VISIT_DURATION_MAX_MIN",
    "OUTPATIENT_VISIT_DURATION_MIN_MIN",
    "OUTPATIENT_VITALS_OFFSET_MIN",
]


# ---------------------------------------------------------------------------
# Visit-timing distributions
# ---------------------------------------------------------------------------

OUTPATIENT_VISIT_DURATION_MIN_MIN: int = 15
"""Lower bound (minutes) of the outpatient visit duration sampled by
``rng.integers(min, max)``.

15 minutes matches the standard short primary-care follow-up slot
(uncomplicated chronic-disease review, single-issue post-discharge
check). Real-world urgent-care and dedicated follow-up appointments
typically block a 15-minute room."""

OUTPATIENT_VISIT_DURATION_MAX_MIN: int = 45
"""Upper bound (minutes, exclusive per ``rng.integers`` convention) of
the outpatient visit duration.

45 minutes captures the longer end of a routine follow-up — new
symptom review, medication reconciliation, patient education. Rarely
exceeded except for annual physicals / new-consult visits which
outpatient.py does not model separately today."""

OUTPATIENT_VITALS_OFFSET_MIN: int = 5
"""Fixed minutes from ``visit_date`` at which outpatient vitals are
captured.

Same convention as ED (``ED_VITALS_OFFSET_MIN``): the triage nurse
records vitals immediately upon rooming, so a deterministic 5-minute
offset from the visit start is a good model of the real workflow."""

OUTPATIENT_LAB_ORDER_OFFSET_MIN: int = 10
"""Fixed minutes from ``visit_date`` at which the outpatient lab order
is placed.

10 minutes after the visit start models the "vitals → brief history →
lab order" outpatient flow. The offset is fixed (not sampled) because
outpatient lab orders queue behind a single provider workflow rather
than the multi-provider parallelism seen in the ED — the timing
variance is negligible."""

OUTPATIENT_LAB_RESULT_OFFSET_HOURS: int = 2
"""Fixed hours from ``visit_date`` at which the outpatient lab result
is reported back.

2 hours matches the standard core-lab turnaround for routine
outpatient chemistry / hematology at an average hospital. Faster than
inpatient because outpatient specimens are prioritized in the "routine
outpatient" batch rather than the "STAT inpatient" batch — but slower
than ED because the ED batch has higher priority."""


# ---------------------------------------------------------------------------
# Prescription defaults
# ---------------------------------------------------------------------------

OUTPATIENT_PRESCRIPTION_DURATION_DAYS: int = 30
"""Default prescription duration (days) for renewals issued at an
outpatient follow-up visit.

30 days is the standard chronic-medication refill interval in both
US (30-day supply is the pharmacy-benefit standard for non-mail-order
pharmacies) and JP (30-day 処方せん is the default for stable chronic
patients under 特定疾患療養管理料 monitoring). Longer intervals
(60 / 90 days) exist but are not modeled today — every outpatient
renewal in ``current_medications`` gets this fixed duration."""
