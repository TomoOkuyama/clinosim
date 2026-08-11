"""Unknown-condition simulator thresholds (Issue #637).

Lifts the previously-inline scalars from
:func:`clinosim.simulator.unknown_condition._simulate_unknown_condition`
into a per-topic threshold file per policy §5. This function models
patients whose presenting condition has no known-disease protocol —
the workup is longer and broader than a known-disease admission, and
the trajectory is a slow random walk rather than an archetype-driven
curve.

Every scalar here fires deterministically off the master RNG (via
``rng.uniform`` / ``rng.integers`` / ``rng.normal`` / ``rng.random``),
so byte-identity of golden cohorts is the required acceptance for the
extraction.

Empirical tuning notes: values were selected to reproduce the
observed shape of "diagnosis-uncertain" admissions in real EHR
extracts — LOS 7-13 days, morning-heavy admission timing (8am-9pm),
and a ~50% "partial resolution" discharge rate.
"""

from __future__ import annotations

__all__ = [
    "UNK_ADMISSION_HOUR_MAX_EXCLUSIVE",
    "UNK_ADMISSION_HOUR_MIN",
    "UNK_ADMISSION_INFLAMMATION_LIFT_MAX",
    "UNK_ADMISSION_INFLAMMATION_LIFT_MIN",
    "UNK_AUTOIMMUNE_WORKUP_DAY",
    "UNK_DAILY_INFLAMMATION_WALK_SD",
    "UNK_DAILY_LAB_HOUR",
    "UNK_DISCHARGE_HOUR",
    "UNK_EXPANDED_IMAGING_HOUR",
    "UNK_INFECTION_TUMOR_WORKUP_DAY",
    "UNK_PARTIAL_RESOLUTION_PROBABILITY",
    "UNK_SUPPORTIVE_MED_PLACEMENT_MIN",
    "UNK_TARGET_LOS_MAX_EXCLUSIVE",
    "UNK_TARGET_LOS_MIN",
    "UNK_WARD_CAPACITY_DEFAULT",
]


# ---------------------------------------------------------------------------
# Admission-time state + timing
# ---------------------------------------------------------------------------

UNK_ADMISSION_INFLAMMATION_LIFT_MIN: float = 0.10
"""Inclusive lower bound of the additive inflammation lift applied at
admission (unknown-condition patients arrive already sick).

Empirical tuning for the synthetic simulator: 10-30% CRP / WBC
elevation matches the observed workup-worthy presentation without
crossing into overt-infection territory."""

UNK_ADMISSION_INFLAMMATION_LIFT_MAX: float = 0.30
"""Exclusive upper bound of the admission inflammation lift."""

UNK_ADMISSION_HOUR_MIN: int = 8
"""Inclusive lower bound of the admission-hour draw (8 AM). Unknown-
condition workups are typically initiated during business hours."""

UNK_ADMISSION_HOUR_MAX_EXCLUSIVE: int = 22
"""Exclusive upper bound of the admission-hour draw (10 PM). Combined
with :data:`UNK_ADMISSION_HOUR_MIN` yields hours 8-21."""


# ---------------------------------------------------------------------------
# Ward + LOS
# ---------------------------------------------------------------------------

UNK_WARD_CAPACITY_DEFAULT: int = 10
"""Fallback ward capacity when ``hospital_ops.ward_capacity`` does not
list the assigned ward. Used only for bed-number generation, does not
affect the actual bed allocation."""

UNK_TARGET_LOS_MIN: int = 7
"""Inclusive lower bound of the target-LOS draw for unknown-condition
patients. Longer than typical known-disease admissions because the
workup is broader and non-conclusive."""

UNK_TARGET_LOS_MAX_EXCLUSIVE: int = 14
"""Exclusive upper bound of the target-LOS draw. Yields LOS 7-13 days
— matches observed workup timelines for diagnosis-uncertain
admissions."""


# ---------------------------------------------------------------------------
# Order placement offsets
# ---------------------------------------------------------------------------

UNK_SUPPORTIVE_MED_PLACEMENT_MIN: int = 30
"""Fixed 30-minute offset from admission_time for supportive
medication orders (acetaminophen, IV fluids, empiric antibiotics).
Not RNG-driven — the unknown-condition path uses fixed offsets to
keep the workup timeline predictable."""

UNK_DAILY_LAB_HOUR: int = 6
"""Hour-of-day (0-23) at which daily monitoring lab orders are
placed. 6 AM matches typical morning-rounds phlebotomy."""

UNK_EXPANDED_IMAGING_HOUR: int = 10
"""Hour-of-day at which the day-4 expanded imaging (CT chest with
contrast) is scheduled. 10 AM aligns with mid-morning radiology
availability."""

UNK_DISCHARGE_HOUR: int = 14
"""Hour-of-day at which the discharge datetime is stamped. 2 PM
matches typical post-lunch discharge planning."""


# ---------------------------------------------------------------------------
# Day-specific workup expansions
# ---------------------------------------------------------------------------

UNK_INFECTION_TUMOR_WORKUP_DAY: int = 2
"""Post-admission day at which infection / tumor markers (Ferritin,
LDH, PCT) are added to the daily lab set. Day 2 = "initial workup
came back inconclusive, broaden the differential"."""

UNK_AUTOIMMUNE_WORKUP_DAY: int = 4
"""Post-admission day at which autoimmune screening (ANA, RF) is
added and expanded imaging (CT chest with contrast) is ordered.
Day 4 = "infection / tumor workup also inconclusive, rule out
autoimmune"."""


# ---------------------------------------------------------------------------
# Trajectory + discharge
# ---------------------------------------------------------------------------

UNK_DAILY_INFLAMMATION_WALK_SD: float = 0.02
"""Standard deviation of the daily inflammation random-walk step.

Empirical tuning for the synthetic simulator: 0.02/day gives a slow
directionless drift consistent with the "no clear trajectory"
character of diagnosis-uncertain admissions."""

UNK_PARTIAL_RESOLUTION_PROBABILITY: float = 0.5
"""Per-admission probability that the unknown condition is coded as
"unresolved" (R50.9 / R53.1) at discharge — the complement is
"partially resolved with nonspecific diagnosis" (R50.9 / R68.8).

Empirical tuning for the synthetic simulator: ~50/50 split matches
the observed disposition-diagnosis distribution in "fever of unknown
origin" and similar workup-heavy cohorts."""
