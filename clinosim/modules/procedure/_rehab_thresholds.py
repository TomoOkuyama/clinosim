"""Post-operative rehabilitation session thresholds (Issue #637).

``generate_rehab_sessions`` in ``clinosim/modules/procedure/engine.py``
simulates a daily PT schedule from post-op day 1 through discharge.
The session-duration, phase cutoffs, pain-model parameters, and
participation sampling constants are lifted here per policy §5.

Byte-diff verification: swapping the inline literals for these named
constants MUST NOT change any RNG-consuming call. ``rng.choice`` /
``rng.normal`` / ``rng.random`` all consume identical bytes whether
the parameters come from literals or module-scope constants.
"""

from __future__ import annotations

__all__ = [
    "REHAB_IMPROVED_MIN_POD",
    "REHAB_JP_SESSION_DURATION_MIN",
    "REHAB_PAIN_BASE_SCORE",
    "REHAB_PAIN_DECAY_PER_POD",
    "REHAB_PAIN_FAIR_PARTICIPATION_THRESHOLD",
    "REHAB_PAIN_MAX_SCORE",
    "REHAB_PAIN_MIN_SCORE",
    "REHAB_PAIN_STD",
    "REHAB_PHASE_EARLY_MAX_POD",
    "REHAB_PHASE_MID_MAX_POD",
    "REHAB_REFUSAL_PROBABILITY",
    "REHAB_SESSION_START_HOUR",
    "REHAB_SKIP_DAY_PROBABILITY",
    "REHAB_START_POD",
    "REHAB_US_SESSION_DURATION_MIN",
]


# ---------------------------------------------------------------------------
# Session scheduling
# ---------------------------------------------------------------------------

REHAB_START_POD: int = 1
"""Post-op day (POD) on which rehabilitation begins.

Standard convention: PT starts POD 1 (the day after surgery) for
uncomplicated post-op patients. Earlier mobilization protocols
(POD 0 same-day PT) exist but are not modeled today."""

REHAB_SESSION_START_HOUR: int = 10
"""Hour-of-day at which each daily rehab session is scheduled.

Empirical tuning for the synthetic simulator: 10:00 fits the typical
mid-morning PT visit window after nursing rounds and breakfast, before
lunch — matches both US and JP inpatient PT norms."""

REHAB_JP_SESSION_DURATION_MIN: int = 40
"""Duration (minutes) of one JP inpatient PT session.

40 minutes matches the standard JP 疾患別リハビリテーション料 unit
(``個別療法 20 分/単位`` × 2 units = 40 min), which is the typical
post-op orthopedic PT block."""

REHAB_US_SESSION_DURATION_MIN: int = 30
"""Duration (minutes) of one US inpatient PT session.

30 minutes is a common US inpatient PT block — shorter than JP's
40-minute unit because US inpatient PT tends to run multiple shorter
sessions per day rather than one longer block."""

REHAB_SKIP_DAY_PROBABILITY: float = 0.1
"""Per-day probability that a scheduled rehab session is skipped.

Empirical tuning for the synthetic simulator: 10% approximates the
combined rate of weekend reductions, holiday closures, and patient
fatigue / medical hold days that prevent PT from running on any given
POD."""


# ---------------------------------------------------------------------------
# Phase boundaries — determine which activity menu is sampled
# ---------------------------------------------------------------------------

REHAB_PHASE_EARLY_MAX_POD: int = 3
"""Maximum POD (inclusive) that falls in the ``early`` rehab phase.

Empirical tuning for the synthetic simulator: PODs 1-3 for
bed-mobility / sit-up / stand-with-assist activities, matching the
typical post-op day-1-to-3 mobilization ladder before walker
ambulation begins."""

REHAB_PHASE_MID_MAX_POD: int = 14
"""Maximum POD (inclusive) that falls in the ``mid`` rehab phase.

Empirical tuning for the synthetic simulator: PODs 4-14 for
walker-ambulation / stair-practice / transfer-training activities.
PODs beyond 14 fall into the ``late`` phase with independent
ambulation and ADL practice."""


# ---------------------------------------------------------------------------
# Pain model
# ---------------------------------------------------------------------------

REHAB_PAIN_BASE_SCORE: float = 4.0
"""Baseline pain score sampled at POD 0 before the daily decay applies.

Empirical tuning for the synthetic simulator: a NRS pain score of 4/10
approximates typical post-op day-1 pain after uncomplicated hip
fracture ORIF under multimodal analgesia (severe unmanaged pain would
be 7+; adequately-managed post-op pain typically sits at 3-5)."""

REHAB_PAIN_DECAY_PER_POD: float = 0.1
"""Amount by which the mean pain score decays per POD.

Empirical tuning for the synthetic simulator: 0.1 NRS/day produces
~1-point pain reduction per 10-day recovery block, matching the
typical convalescence trajectory for uncomplicated post-op patients."""

REHAB_PAIN_STD: float = 1.5
"""Standard deviation (NRS points) of the daily pain-score distribution.

Empirical tuning for the synthetic simulator: 1.5 NRS keeps ~95% of
sampled scores within ±3 points of the day's mean — matches the
day-to-day variability seen in real post-op pain charts."""

REHAB_PAIN_MIN_SCORE: int = 0
"""Minimum allowed integer pain score (NRS floor)."""

REHAB_PAIN_MAX_SCORE: int = 10
"""Maximum allowed integer pain score (NRS ceiling)."""


# ---------------------------------------------------------------------------
# Participation and progress
# ---------------------------------------------------------------------------

REHAB_PAIN_FAIR_PARTICIPATION_THRESHOLD: int = 6
"""Pain score strictly above which participation drops from ``good`` to
``fair``.

Empirical tuning for the synthetic simulator: NRS 7+ is the widely-used
threshold for "severe pain requiring intervention", above which PT
participation is meaningfully impaired even with encouragement."""

REHAB_REFUSAL_PROBABILITY: float = 0.05
"""Per-session probability that a patient refuses rehabilitation.

Empirical tuning for the synthetic simulator: 5% reflects the small
fraction of sessions declined for reasons other than pain (fatigue,
low mood, competing procedures)."""

REHAB_IMPROVED_MIN_POD: int = 3
"""Post-op day strictly above which functional progress is reported as
``improved`` rather than ``stable``.

Empirical tuning for the synthetic simulator: PODs 1-3 are typically
too early to observe meaningful functional improvement in PT notes;
from POD 4 onward the daily gains become documentable."""
