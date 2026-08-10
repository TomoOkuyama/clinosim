"""Daily-loop workflow thresholds (Issue #637).

``clinosim/simulator/daily_loop.py::run_daily_loop`` orchestrates each
inpatient day: physiology update, lab-order placement (with morning-
draw jitter + severity/discharge/weekend/late-stay frequency
modulation), archetype-driven order/treatment modifications (with
±1 day jitter for realism), treatment escalation trigger, and diet
advancement.

Every scalar the loop previously carried inline is lifted here per
policy §5. The frequency multipliers are empirical (calibrated
against observed inpatient lab-ordering intensity vs discharge
proximity), the diet-advancement inflammation thresholds are matched
to typical inpatient recovery trajectories.

Byte-diff verification: swapping the inline literals for these named
constants MUST NOT change any RNG-consuming call. ``rng.random`` /
``rng.integers`` / ``rng.choice`` consume identical bytes whether the
arguments come from literals or module-scope constants.
"""

from __future__ import annotations

__all__ = [
    "ARCHETYPE_DAY_SHIFT_PROBABILITY",
    "DIET_CLEAR_LIQUID_INFLAMMATION_THRESHOLD",
    "DIET_SOFT_INFLAMMATION_THRESHOLD",
    "LAB_EARLY_MORNING_HOUR",
    "LAB_EARLY_MORNING_MIN_END_EXCLUSIVE",
    "LAB_EARLY_MORNING_MIN_START",
    "LAB_EARLY_MORNING_PROBABILITY",
    "LAB_FREQ_MULT_LATE_STAY_STABLE",
    "LAB_FREQ_MULT_NEAR_DISCHARGE",
    "LAB_FREQ_MULT_SEVERITY_FALLBACK",
    "LAB_FREQ_MULT_SEVERITY_MILD",
    "LAB_FREQ_MULT_SEVERITY_MODERATE",
    "LAB_FREQ_MULT_SEVERITY_SEVERE",
    "LAB_FREQ_MULT_WEEKEND",
    "LAB_LATE_STAY_INFLAMMATION_MAX",
    "LAB_LATE_STAY_MIN_DAY",
    "LAB_MIN_END_EXCLUSIVE",
    "LAB_MIN_START",
    "LAB_MORNING_HOUR",
    "LAB_NEAR_DISCHARGE_INFLAMMATION_MAX",
    "LAB_NEAR_DISCHARGE_DAY_OFFSET",
    "TREATMENT_ESCALATION_DAY",
    "TREATMENT_ESCALATION_INFLAMMATION_MIN",
]


# ---------------------------------------------------------------------------
# Morning lab-draw timing
# ---------------------------------------------------------------------------

LAB_MORNING_HOUR: int = 6
"""Default hour for the morning lab draw — matches typical inpatient
"6 AM AM labs" convention."""

LAB_MIN_START: int = 0
"""Inclusive lower bound for the morning-lab minute jitter."""

LAB_MIN_END_EXCLUSIVE: int = 45
"""Exclusive upper bound for the morning-lab minute jitter (0-44 min
past 6 AM)."""

LAB_EARLY_MORNING_PROBABILITY: float = 0.2
"""Probability the lab draw shifts to the 5:30-6:00 pre-6-AM window
(e.g., pre-round nursing draws for early-round rounds).

Empirical tuning for the synthetic simulator: 20% approximates the
minority of hospital wards that do 5:30-6:00 pre-round draws vs the
6:00-7:00 majority."""

LAB_EARLY_MORNING_HOUR: int = 5
"""Hour used for the pre-6-AM early-morning-lab branch."""

LAB_EARLY_MORNING_MIN_START: int = 30
"""Inclusive lower bound for the early-morning-lab minute jitter
(5:30)."""

LAB_EARLY_MORNING_MIN_END_EXCLUSIVE: int = 60
"""Exclusive upper bound for the early-morning-lab minute jitter
(30-59 min, giving 5:30-5:59)."""


# ---------------------------------------------------------------------------
# Lab-frequency severity multipliers
# ---------------------------------------------------------------------------

LAB_FREQ_MULT_SEVERITY_SEVERE: float = 1.3
"""Multiplier applied to routine-lab frequency for severe severity —
sicker patients get more frequent monitoring."""

LAB_FREQ_MULT_SEVERITY_MODERATE: float = 1.0
"""Multiplier applied for moderate severity (identity)."""

LAB_FREQ_MULT_SEVERITY_MILD: float = 0.6
"""Multiplier applied for mild severity — less-sick patients get
lower-cadence labs."""

LAB_FREQ_MULT_SEVERITY_FALLBACK: float = 1.0
"""Fallback multiplier when the severity label is not one of
severe/moderate/mild (defaults to moderate cadence)."""


# ---------------------------------------------------------------------------
# Near-discharge lab-frequency reduction
# ---------------------------------------------------------------------------

LAB_NEAR_DISCHARGE_DAY_OFFSET: int = 2
"""Number of days before ``target_los`` at which the near-discharge
lab-frequency reduction fires (combined with the inflammation cap)."""

LAB_NEAR_DISCHARGE_INFLAMMATION_MAX: float = 0.1
"""``inflammation_level`` strictly below which the near-discharge
lab-frequency reduction fires."""

LAB_FREQ_MULT_NEAR_DISCHARGE: float = 0.5
"""Multiplier applied to lab frequency when the patient is near
discharge AND clinically stable — halves routine draws in the
prepare-for-discharge phase."""


# ---------------------------------------------------------------------------
# Weekend + late-stay lab-frequency reductions
# ---------------------------------------------------------------------------

LAB_FREQ_MULT_WEEKEND: float = 0.7
"""Multiplier applied to non-urgent lab frequency on weekends —
approximates the reduced weekend nursing / phlebotomy staffing."""

LAB_LATE_STAY_MIN_DAY: int = 7
"""Post-admission day at or above which the late-stay-stable
lab-frequency reduction may fire (combined with the inflammation
cap)."""

LAB_LATE_STAY_INFLAMMATION_MAX: float = 0.15
"""``inflammation_level`` strictly below which the late-stay-stable
lab-frequency reduction fires."""

LAB_FREQ_MULT_LATE_STAY_STABLE: float = 0.8
"""Multiplier applied when the patient has been stable past the
late-stay day threshold."""


# ---------------------------------------------------------------------------
# Archetype ±1 day jitter (order/treatment modification timing)
# ---------------------------------------------------------------------------

ARCHETYPE_DAY_SHIFT_PROBABILITY: float = 0.3
"""Probability that an archetype-day-N order/treatment modification
fires on an adjacent day (day N-1 or N+1) instead of exactly day N.

Empirical tuning for the synthetic simulator: 30% ±1-day jitter
reflects clinical-workflow variability — some days a planned
treatment is delayed by one day (holiday, patient unavailability)
or advanced (rounds ran ahead)."""


# ---------------------------------------------------------------------------
# Treatment escalation
# ---------------------------------------------------------------------------

TREATMENT_ESCALATION_DAY: int = 3
"""Post-admission day on which the "not improving → escalate" gate
fires."""

TREATMENT_ESCALATION_INFLAMMATION_MIN: float = 0.3
"""``inflammation_level`` strictly above which day-3 treatment
escalation is triggered.

Empirical tuning for the synthetic simulator: PODs 3+ still-inflamed
patients (level > 0.3) plausibly failed first-line therapy and need
escalation (second-line antibiotics, escalated fluid resuscitation,
etc.)."""


# ---------------------------------------------------------------------------
# Diet advancement (NPO → clear_liquid → soft → regular)
# ---------------------------------------------------------------------------

DIET_CLEAR_LIQUID_INFLAMMATION_THRESHOLD: float = 0.3
"""``inflammation_level`` strictly above which day-1 patients stay on
clear liquids (below advances to soft diet).

Empirical tuning for the synthetic simulator: 0.3 approximately marks
the boundary between "acute-illness gut" (clear liquids only) and
"tolerating soft diet"."""

DIET_SOFT_INFLAMMATION_THRESHOLD: float = 0.2
"""``inflammation_level`` strictly above which post-day-1 patients
stay on soft diet (below advances to regular diet).

Empirical tuning for the synthetic simulator: 0.2 marks the boundary
below which resolved acute inflammation allows normal diet."""
