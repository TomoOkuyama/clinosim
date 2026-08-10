"""Vitals-scheduling thresholds for the inpatient daily vitals loop (Issue #637).

``clinosim/simulator/vitals_pipeline.py::_generate_vitals`` decides the
per-day vitals cadence (q2h / q4h / q6h / bid / tid) based on acuity
markers and length of stay, then samples per-observation time jitters,
pain-score offsets, and nursing-note trigger thresholds.

Every scalar the function previously carried inline is lifted here per
policy §5. Companion to PR #685 (`_adl_thresholds`, `_oxygen_therapy_thresholds`,
`_loc_thresholds`) and PR #688 (`_daily_io_thresholds`).

Byte-diff verification: swapping the inline literals for these named
constants MUST NOT change any RNG-consuming call. ``rng.normal`` /
``list(range(...))`` produce identical sequences whether their
arguments come from literals or module-scope constants.
"""

from __future__ import annotations

__all__ = [
    "VITALS_ACUITY_INFLAMMATION_UNSTABLE_THRESHOLD",
    "VITALS_ACUITY_PERFUSION_CRITICAL_THRESHOLD",
    "VITALS_ACUITY_PERFUSION_UNSTABLE_THRESHOLD",
    "VITALS_BID_STABLE_HOURS",
    "VITALS_BID_STABLE_INFLAMMATION_MAX",
    "VITALS_BID_STABLE_MIN_DAY",
    "VITALS_CRITICAL_DAY_MAX",
    "VITALS_EARLY_DAY_MAX",
    "VITALS_FULL_JITTER_MIN_SD",
    "VITALS_IMPROVING_NOTE_INFLAMMATION_MAX",
    "VITALS_IMPROVING_NOTE_MIN_DAY",
    "VITALS_MONITOR_HOURS_END_EXCLUSIVE",
    "VITALS_MONITOR_HOURS_START",
    "VITALS_MONITOR_HOURS_STEP",
    "VITALS_MONITOR_JITTER_MIN_SD",
    "VITALS_PAIN_EARLY_DAY_LIFT",
    "VITALS_PAIN_INFLAMMATION_SCALE",
    "VITALS_PAIN_MAX",
    "VITALS_PAIN_MIN",
    "VITALS_PAIN_NOISE_SD",
    "VITALS_Q2H_HOURS_END_EXCLUSIVE",
    "VITALS_Q2H_HOURS_START",
    "VITALS_Q2H_HOURS_STEP",
    "VITALS_Q4H_HOURS",
    "VITALS_Q6H_HOURS",
    "VITALS_SPO2_LOW_NOTE_THRESHOLD",
    "VITALS_TID_HOURS",
]


# ---------------------------------------------------------------------------
# Acuity markers — determine which schedule ladder fires
# ---------------------------------------------------------------------------

VITALS_ACUITY_PERFUSION_UNSTABLE_THRESHOLD: float = 0.5
"""``perfusion_status`` strictly below which the patient is flagged
unstable for vitals-scheduling purposes.

Empirical tuning for the synthetic simulator: 0.5 is the mid-scale
cutoff — patients here get q4h vitals if not already critical."""

VITALS_ACUITY_INFLAMMATION_UNSTABLE_THRESHOLD: float = 0.5
"""``inflammation_level`` strictly above which the patient is flagged
unstable for vitals-scheduling purposes (same 0.5 mid-scale
cutoff as perfusion). Either marker satisfies the "unstable"
condition."""

VITALS_ACUITY_PERFUSION_CRITICAL_THRESHOLD: float = 0.3
"""``perfusion_status`` strictly below which the patient is flagged
critical, escalating to q2h vitals during the early acute window.

Cross-reference: 0.3 matches the low-perfusion critical mortality
multiplier trigger (``MORTALITY_LOW_PERFUSION_THRESHOLD`` in
``_discharge_gate_thresholds.py``) — the two constants intentionally
share the same threshold since both mark "critically hypoperfused"."""


# ---------------------------------------------------------------------------
# Day boundaries for schedule ladder
# ---------------------------------------------------------------------------

VITALS_CRITICAL_DAY_MAX: int = 2
"""Post-op day (inclusive) at or below which critical patients get
q2h vitals; beyond this day they drop to the unstable q4h cadence.

Empirical tuning for the synthetic simulator: PODs 0-2 cover the
acute window when critical patients need close monitoring; sustained
critical illness beyond this is rare, and continued q2h vitals become
resource-prohibitive."""

VITALS_EARLY_DAY_MAX: int = 2
"""Post-op day (inclusive) at or below which stable patients still get
q6h vitals (before dropping to tid/bid).

Same 2-day window as :data:`VITALS_CRITICAL_DAY_MAX` — the first
48 hours post-admission carry higher observational cadence across
all acuity levels."""

VITALS_BID_STABLE_MIN_DAY: int = 7
"""Post-op day at or above which very-stable patients can drop to
bid vitals.

Empirical tuning for the synthetic simulator: sustained stability past
POD 7 (typical LOS mid-to-late) makes bid vitals appropriate; earlier
than this, the observational cadence stays at tid to catch any
deterioration."""

VITALS_BID_STABLE_INFLAMMATION_MAX: float = 0.1
"""``inflammation_level`` strictly below which a late-stay patient can
drop to bid vitals — combined with :data:`VITALS_BID_STABLE_MIN_DAY`.

0.1 approximates near-resolved inflammation."""


# ---------------------------------------------------------------------------
# Hour-of-day schedule blocks (24-hour lists)
# ---------------------------------------------------------------------------

VITALS_Q2H_HOURS_START: int = 0
"""Starting hour of the q2h critical vitals schedule."""

VITALS_Q2H_HOURS_END_EXCLUSIVE: int = 24
"""Exclusive end hour of the q2h critical vitals schedule."""

VITALS_Q2H_HOURS_STEP: int = 2
"""Step in hours of the q2h critical vitals schedule
(0, 2, 4, …, 22 — 12 sets/day)."""

VITALS_Q4H_HOURS: tuple[int, int, int, int, int, int] = (2, 6, 10, 14, 18, 22)
"""Hour-of-day list for the q4h unstable-patient vitals schedule
(6 sets/day, offset by 2h from the q2h grid to spread nursing load)."""

VITALS_Q6H_HOURS: tuple[int, int, int, int] = (0, 6, 12, 18)
"""Hour-of-day list for the q6h early-stay stable vitals schedule
(4 sets/day, hours align with typical nursing shift changes)."""

VITALS_BID_STABLE_HOURS: tuple[int, int] = (6, 18)
"""Hour-of-day list for the bid late-stay stable vitals schedule
(2 sets/day at 6 AM / 6 PM shift starts)."""

VITALS_TID_HOURS: tuple[int, int, int] = (6, 14, 22)
"""Hour-of-day list for the tid default vitals schedule
(3 sets/day, ~q8h spacing)."""


# ---------------------------------------------------------------------------
# Monitoring hours (HR + SpO2 continuous, alternating with full vitals)
# ---------------------------------------------------------------------------

VITALS_MONITOR_HOURS_START: int = 1
"""Starting hour of the continuous-monitoring odd-hour grid
(1, 3, 5, … — chosen to interleave with the even-hour q2h/q4h
grids so vitals + monitoring never collide)."""

VITALS_MONITOR_HOURS_END_EXCLUSIVE: int = 24
"""Exclusive end hour of the continuous-monitoring grid."""

VITALS_MONITOR_HOURS_STEP: int = 2
"""Step in hours of the continuous-monitoring grid."""


# ---------------------------------------------------------------------------
# Per-observation time jitter (min-SD in minutes)
# ---------------------------------------------------------------------------

VITALS_FULL_JITTER_MIN_SD: float = 10.0
"""Standard deviation (minutes) of the jitter applied to the scheduled
full-vitals timestamp — models real-world nursing variability where
the "10 AM round" can fall anywhere from 9:40 to 10:20."""

VITALS_MONITOR_JITTER_MIN_SD: float = 5.0
"""Standard deviation (minutes) of the jitter applied to the scheduled
continuous-monitor timestamp — smaller than the full-vitals jitter
because monitor devices produce timestamps automatically, so the
variability is only in the exact sync/upload moment."""


# ---------------------------------------------------------------------------
# Pain-score model (produced on the full-vitals set only)
# ---------------------------------------------------------------------------

VITALS_PAIN_INFLAMMATION_SCALE: float = 4.0
"""Multiplier applied to ``inflammation_level`` in the base pain-score
model — inflammation 0-1 contributes 0-4 NRS points."""

VITALS_PAIN_EARLY_DAY_LIFT: float = 2.0
"""Additive lift applied to the base pain score during the early
post-admission window (PODs 0-2).

Empirical tuning for the synthetic simulator: +2 NRS points reflects
the acute-post-admission pain premium — patients newly admitted with
severe inflammation cluster in the upper half of the NRS."""

VITALS_PAIN_NOISE_SD: float = 1.5
"""Standard deviation of the pain-score noise draw (NRS points).

Same convention as :data:`REHAB_PAIN_STD` (post-op rehab): NRS pain
carries meaningful patient-to-patient reporting variability."""

VITALS_PAIN_MIN: int = 0
"""Lower bound (integer) of the 0-10 NRS pain scale."""

VITALS_PAIN_MAX: int = 10
"""Upper bound (integer) of the 0-10 NRS pain scale."""


# ---------------------------------------------------------------------------
# Nursing-note trigger thresholds
# ---------------------------------------------------------------------------

VITALS_SPO2_LOW_NOTE_THRESHOLD: float = 93.0
"""``spo2`` strictly below which the nursing note flags "SpO2 low,
O2 adjusted".

93% is the widely-cited SpO2 cutoff below which supplemental O2
adjustment is typically indicated for non-COPD patients; not the
same as the therapy-triggering :data:`SPO2_HYPOXEMIA_TRIGGER` (95%),
which is a lower-threshold observational-flag alert."""

VITALS_IMPROVING_NOTE_INFLAMMATION_MAX: float = 0.1
"""``inflammation_level`` strictly below which the nursing note flags
"improving, appetite good" (combined with
:data:`VITALS_IMPROVING_NOTE_MIN_DAY`).

0.1 approximates near-resolved inflammation — same cutoff as
:data:`VITALS_BID_STABLE_INFLAMMATION_MAX` for logical consistency."""

VITALS_IMPROVING_NOTE_MIN_DAY: int = 3
"""Post-op day at or above which the "improving, appetite good" nursing
note can fire — combined with the inflammation cutoff above.

Empirical tuning for the synthetic simulator: PODs 0-2 are too early
for a meaningful "improving" observation; from POD 3 onward the
trend is documentable in nursing notes."""
