"""ADL (Barthel Index) assessment thresholds (Issue #637).

``clinosim/simulator/vitals_pipeline.py::_generate_adl_assessment``
generates a daily Barthel Index score for each inpatient, driven by
age, clinical state, and length-of-stay. The score gets a normal-noise
jitter and is then decomposed into the standard 10 Barthel components
with proportional weighting.

Every scalar the function previously carried inline is lifted here per
policy §5. The Barthel component maximums are Barthel-standard (feeding
10, bathing 5, grooming 5, dressing 10, bowels 10, bladder 10, toilet
10, transfers 15, mobility 15, stairs 10 — total 100); the per-component
ratio-offset tweaks are simulator-empirical adjustments so that easier
tasks (feeding, grooming, bowel/bladder control) recover before harder
tasks (stairs) at the same ratio.

Byte-diff verification: swapping the inline literals for these named
constants MUST NOT change any RNG-consuming call. ``rng.normal``
consumes identical bytes whether its arguments come from literals or
module-scope constants.
"""

from __future__ import annotations

__all__ = [
    "ADL_ACUITY_FULL_AT",
    "ADL_MAX_GAIN_PER_ASSESSMENT",
    "ADL_ASSESSMENT_INTERVAL_DAYS",
    "ADL_BARTHEL_MAX",
    "ADL_BARTHEL_MIN",
    "ADL_BARTHEL_NOISE_SD",
    "ADL_COMP_BATHING_MAX",
    "ADL_COMP_BOWEL_MAX",
    "ADL_COMP_BLADDER_MAX",
    "ADL_COMP_DRESSING_MAX",
    "ADL_COMP_FEEDING_MAX",
    "ADL_COMP_GROOMING_MAX",
    "ADL_COMP_MOBILITY_MAX",
    "ADL_COMP_STAIRS_MAX",
    "ADL_COMP_TOILET_MAX",
    "ADL_COMP_TRANSFERS_MAX",
    "ADL_DAY0_ACUTE_PENALTY",
    "ADL_INFLAMMATION_PENALTY_SCALE",
    "ADL_OLDEST_AGE_PENALTY",
    "ADL_OLDEST_AGE_THRESHOLD",
    "ADL_OLDER_AGE_PENALTY",
    "ADL_OLDER_AGE_THRESHOLD",
    "ADL_PERFUSION_PENALTY_SCALE",
    "ADL_RENAL_PENALTY_SCALE",
    "ADL_RATIO_OFFSET_BLADDER",
    "ADL_RATIO_OFFSET_BOWEL",
    "ADL_RATIO_OFFSET_FEEDING",
    "ADL_RATIO_OFFSET_GROOMING",
    "ADL_RATIO_OFFSET_STAIRS_DEFICIT",
]


# ---------------------------------------------------------------------------
# Assessment scheduling
# ---------------------------------------------------------------------------

ADL_ASSESSMENT_INTERVAL_DAYS: int = 7
"""Interval (days) between recurring ADL assessments after admission.

Standard convention: ADL is assessed on admission (day 0), then
weekly (day 7, 14, ...), plus at discharge — matches JP 回復期
リハビリテーション and US inpatient PT documentation cadence."""


# ---------------------------------------------------------------------------
# Barthel base score + age adjustments
# ---------------------------------------------------------------------------

ADL_BARTHEL_MAX: int = 100
"""Maximum Barthel Index score (100 = fully independent)."""

ADL_BARTHEL_MIN: int = 0
"""Minimum Barthel Index score (0 = totally dependent)."""

ADL_OLDEST_AGE_THRESHOLD: int = 85
"""Patient age at or above which the largest baseline ADL penalty is
applied."""

ADL_OLDEST_AGE_PENALTY: int = 20
"""Baseline Barthel points subtracted for ``age >= ADL_OLDEST_AGE_THRESHOLD``.

Empirical tuning for the synthetic simulator: 20-point drop reflects
the substantial functional decline observed in the ≥85 cohort at
inpatient admission."""

ADL_OLDER_AGE_THRESHOLD: int = 75
"""Patient age at or above (but below the oldest threshold) which the
smaller baseline ADL penalty is applied."""

ADL_OLDER_AGE_PENALTY: int = 10
"""Baseline Barthel points subtracted for
``ADL_OLDER_AGE_THRESHOLD <= age < ADL_OLDEST_AGE_THRESHOLD``.

Empirical tuning for the synthetic simulator: 10-point drop for
the 75-84 bracket — gentler than the ≥85 bracket."""


# ---------------------------------------------------------------------------
# Clinical-state penalties (each scales a 0-1 axis into Barthel points)
# ---------------------------------------------------------------------------

ADL_INFLAMMATION_PENALTY_SCALE: int = 30
"""Barthel-point scale applied to ``inflammation_level`` (0-1 axis).

Empirical tuning for the synthetic simulator: severe inflammation
(level ≈ 1.0) removes 30 Barthel points, matching the observation
that acutely inflamed patients cannot perform full ADL."""

ADL_PERFUSION_PENALTY_SCALE: int = 20
"""Barthel-point scale applied to ``(1 - perfusion_status)``.

Empirical tuning for the synthetic simulator: complete hemodynamic
failure removes 20 Barthel points — smaller than inflammation because
perfusion decline manifests more as fatigue than as absolute inability."""

ADL_RENAL_PENALTY_SCALE: int = 10
"""Barthel-point scale applied to ``(1 - renal_function)``.

Empirical tuning for the synthetic simulator: complete renal failure
removes 10 Barthel points — the smallest of the three because renal
insufficiency's ADL impact is indirect (fatigue, dialysis-imposed
immobility) rather than immediate."""


# ---------------------------------------------------------------------------
# Acute-illness penalty (full on admission day, scaled by acuity later) and the
# per-assessment gain cap
# ---------------------------------------------------------------------------

ADL_DAY0_ACUTE_PENALTY: int = 15
"""Additional Barthel-point penalty applied in full on admission day
(day 0), and scaled by the state's acuity on later days (Issue #3647), on top
of the state-based penalties.

Empirical tuning for the synthetic simulator: acute-admission-day
ADL is systematically lower than any post-admission day at the same
physiological state — captures the "just arrived, disoriented" effect
that resolves within 24 hours."""

ADL_ACUITY_FULL_AT: float = 0.5
"""Acuity (the worst of the inflammation level, the oxygenation impairment and
the perfusion deficit) at or above which the full acute-illness penalty
(``ADL_DAY0_ACUTE_PENALTY``) applies to a later assessment; below it the penalty
scales down linearly to zero as the state resolves (Issue #3647). A modelling
choice: function recovers with the clinical state, not with elapsed days."""

ADL_MAX_GAIN_PER_ASSESSMENT: int = 20
"""Largest Barthel gain, in points, between one assessment and the next of
the same stay (Issue #3647). A modelling choice that stops a single step of
30-45 points; the drop of a worsening patient is not capped."""

ADL_BARTHEL_NOISE_SD: int = 5
"""Standard deviation of the normal-noise jitter applied to the
computed Barthel score.

Empirical tuning for the synthetic simulator: 5-point SD keeps day-to-
day scores realistic — the underlying model produces a smooth
trajectory, and this noise adds day-level scoring variability."""


# ---------------------------------------------------------------------------
# Component maximums (standard Barthel Index)
# ---------------------------------------------------------------------------
# Sum: 10+5+5+10+10+10+10+15+15+10 = 100 (Barthel max)

ADL_COMP_FEEDING_MAX: int = 10
"""Max Barthel points for feeding (standard Barthel)."""

ADL_COMP_BATHING_MAX: int = 5
"""Max Barthel points for bathing (standard Barthel)."""

ADL_COMP_GROOMING_MAX: int = 5
"""Max Barthel points for grooming (standard Barthel)."""

ADL_COMP_DRESSING_MAX: int = 10
"""Max Barthel points for dressing (standard Barthel)."""

ADL_COMP_BOWEL_MAX: int = 10
"""Max Barthel points for bowel control (standard Barthel)."""

ADL_COMP_BLADDER_MAX: int = 10
"""Max Barthel points for bladder control (standard Barthel)."""

ADL_COMP_TOILET_MAX: int = 10
"""Max Barthel points for toilet use (standard Barthel)."""

ADL_COMP_TRANSFERS_MAX: int = 15
"""Max Barthel points for transfers (standard Barthel)."""

ADL_COMP_MOBILITY_MAX: int = 15
"""Max Barthel points for mobility (standard Barthel)."""

ADL_COMP_STAIRS_MAX: int = 10
"""Max Barthel points for stairs (standard Barthel)."""


# ---------------------------------------------------------------------------
# Component ratio offsets — modulate each component's recovery relative
# to the overall Barthel ratio, so easier ADLs recover before harder
# ones at the same ratio.
# ---------------------------------------------------------------------------

ADL_RATIO_OFFSET_FEEDING: float = 0.1
"""Additive offset to the base ratio for feeding — easier ADL, recovers
sooner than the average trajectory."""

ADL_RATIO_OFFSET_GROOMING: float = 0.1
"""Additive offset to the base ratio for grooming — easier ADL,
recovers sooner than the average trajectory."""

ADL_RATIO_OFFSET_BOWEL: float = 0.2
"""Additive offset to the base ratio for bowel control — most patients
retain bowel continence even at low overall function."""

ADL_RATIO_OFFSET_BLADDER: float = 0.15
"""Additive offset to the base ratio for bladder control — same
rationale as bowel control, slightly smaller offset because acute
urinary incontinence is more common than bowel incontinence in
inpatients."""

ADL_RATIO_OFFSET_STAIRS_DEFICIT: float = 0.2
"""Subtractive offset from the base ratio for stairs — hardest ADL,
recovers last."""
