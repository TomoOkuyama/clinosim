"""Clinical-course residual thresholds (Issue #637).

Companion to :mod:`clinosim.modules.clinical_course._archetype_modifiers`
(which covers per-archetype delta / speed multipliers): this file
lifts the previously-inline scalars from three remaining functions in
``clinical_course/engine.py`` per policy §5:

1. ``get_daily_directive`` — occasional non-monotonic "bump day"
   trajectory noise (probability + amplitude).
2. ``compute_diagnosis_effectiveness`` /
   ``apply_diagnosis_modifier`` — the effectiveness curve mapping
   (working diagnosis, confidence, difficulty) → treatment
   effectiveness in [0.05, 1.0].
3. ``natural_recovery_directive`` — daily baseline recovery deltas
   independent of treatment (immune-driven inflammation resolution,
   volume normalization, bone-marrow erythropoiesis).

Byte-diff verification: swapping the inline literals for these named
constants MUST NOT change any RNG-consuming call. ``rng.random`` /
``rng.normal`` consume identical bytes whether their arguments come
from literals or module-scope constants.
"""

from __future__ import annotations

__all__ = [
    "ANEMIA_RECOVERY_ACCEL_MIN_DAY",
    "ANEMIA_RECOVERY_ACCEL_RATE",
    "ANEMIA_RECOVERY_BASE_RATE",
    "ANEMIA_RECOVERY_STEADY_MIN_DAY",
    "ANEMIA_RECOVERY_STEADY_RATE",
    "BUMP_DAY_PROBABILITY",
    "BUMP_DAY_STD",
    "DIAGNOSIS_CORRECT_HIGH_CONF_BASE",
    "DIAGNOSIS_CORRECT_HIGH_CONF_SCALE",
    "DIAGNOSIS_CORRECT_LOW_CONF_BASE",
    "DIAGNOSIS_CORRECT_LOW_CONF_SCALE",
    "DIAGNOSIS_CONFIDENCE_THRESHOLD_BASE",
    "DIAGNOSIS_CONFIDENCE_THRESHOLD_DIFFICULTY_SCALE",
    "DIAGNOSIS_DIFFICULTY_DEFAULT",
    "DIAGNOSIS_EFFECTIVENESS_MAX",
    "DIAGNOSIS_EMPIRIC_BASE",
    "DIAGNOSIS_EMPIRIC_DIFFICULTY_SCALE",
    "DIAGNOSIS_EMPIRIC_FLOOR",
    "DIAGNOSIS_FULL_EFFECTIVE_THRESHOLD",
    "DIAGNOSIS_WRONG_BASE",
    "DIAGNOSIS_WRONG_DIFFICULTY_SCALE",
    "DIAGNOSIS_WRONG_FLOOR",
    "NATURAL_RECOVERY_BASE_RATE",
    "NATURAL_RECOVERY_LATE_DECAY_FACTOR",
    "NATURAL_RECOVERY_LATE_MIN_DAY",
    "NATURAL_RECOVERY_MID_DECAY_FACTOR",
    "NATURAL_RECOVERY_MID_MIN_DAY",
    "NATURAL_RECOVERY_SEVERITY_MILD",
    "NATURAL_RECOVERY_SEVERITY_MODERATE",
    "NATURAL_RECOVERY_SEVERITY_MULT_FALLBACK",
    "NATURAL_RECOVERY_SEVERITY_SEVERE",
    "VOLUME_RECOVERY_RATE_PER_UNIT_SEVERITY",
]


# ---------------------------------------------------------------------------
# Trajectory noise — occasional "bump day" perturbation
# ---------------------------------------------------------------------------

BUMP_DAY_PROBABILITY: float = 0.10
"""Per-day probability of a larger non-monotonic perturbation on top
of the proportional daily noise.

Empirical tuning for the synthetic simulator: 10% frequency produces
"bump days" (e.g. a CRP that jumps on POD 4 despite improving
inflammation) at a realistic rate — real clinical trajectories are
never perfectly monotonic."""

BUMP_DAY_STD: float = 0.008
"""Standard deviation of the bump-day perturbation (state-var units,
0-1 scale).

Empirical tuning for the synthetic simulator: 0.008 gives a
meaningful but non-catastrophic perturbation — a 1-sigma bump moves a
state variable by less than 1% of its full range."""


# ---------------------------------------------------------------------------
# Diagnosis effectiveness — empiric therapy branch
# ---------------------------------------------------------------------------

DIAGNOSIS_DIFFICULTY_DEFAULT: float = 0.3
"""Default diagnostic difficulty passed to
:func:`compute_diagnosis_effectiveness` when the caller does not
supply one.

Empirical tuning for the synthetic simulator: 0.3 sits below the mid-
range — most diseases modeled today are moderately-to-easily
diagnosable, so 0.3 approximates the average case."""

DIAGNOSIS_EMPIRIC_FLOOR: float = 0.15
"""Minimum effectiveness of empiric therapy (no working diagnosis) —
prevents effectiveness from collapsing to zero even for very-hard-
to-diagnose conditions."""

DIAGNOSIS_EMPIRIC_BASE: float = 0.4
"""Base effectiveness of empiric therapy at ``diagnostic_difficulty = 0``.

Empirical tuning for the synthetic simulator: 40% baseline means
trivially-diagnosable conditions still see meaningful empiric-therapy
gains even without a formal working diagnosis (e.g. supportive care,
IV fluids)."""

DIAGNOSIS_EMPIRIC_DIFFICULTY_SCALE: float = 0.2
"""Reduction in empiric-therapy effectiveness per unit of
``diagnostic_difficulty``.

Empirical tuning for the synthetic simulator: 0.2 gives empiric-
therapy effectiveness of ``0.4 - 0.2 * difficulty``, ranging from
0.4 (trivial) to 0.2 (max difficulty) before the floor kicks in."""


# ---------------------------------------------------------------------------
# Diagnosis effectiveness — correct-diagnosis branch
# ---------------------------------------------------------------------------

DIAGNOSIS_CONFIDENCE_THRESHOLD_BASE: float = 0.3
"""Base confidence threshold above which the "high-confidence"
effectiveness formula fires when the diagnosis is correct.

Empirical tuning for the synthetic simulator: 0.3 is a modest
confidence bar for trivial diseases; harder diseases require more via
:data:`DIAGNOSIS_CONFIDENCE_THRESHOLD_DIFFICULTY_SCALE`."""

DIAGNOSIS_CONFIDENCE_THRESHOLD_DIFFICULTY_SCALE: float = 0.3
"""Per-unit-difficulty lift added to
:data:`DIAGNOSIS_CONFIDENCE_THRESHOLD_BASE`.

At max difficulty, the confidence threshold rises to 0.6 — matching
the intuition that a maximally-hard diagnosis needs high confidence
before it's treated with full effectiveness."""

DIAGNOSIS_CORRECT_HIGH_CONF_BASE: float = 0.6
"""Base effectiveness for a correct high-confidence diagnosis."""

DIAGNOSIS_CORRECT_HIGH_CONF_SCALE: float = 0.4
"""Confidence-scaling factor for a correct high-confidence diagnosis.

Effectiveness = ``min(1.0, 0.6 + confidence * 0.4)``, saturating at 1.0
for confidence ≥ 1.0."""

DIAGNOSIS_CORRECT_LOW_CONF_BASE: float = 0.4
"""Base effectiveness for a correct diagnosis at low confidence
(below the confidence threshold)."""

DIAGNOSIS_CORRECT_LOW_CONF_SCALE: float = 0.5
"""Confidence-scaling factor for a correct low-confidence diagnosis.

Effectiveness = ``min(1.0, 0.4 + confidence * 0.5)``, so at
confidence just below the threshold the low-conf branch still gives a
non-trivial 0.5-0.6 range."""

DIAGNOSIS_EFFECTIVENESS_MAX: float = 1.0
"""Ceiling on the diagnosis-effectiveness score (fully-effective
treatment)."""


# ---------------------------------------------------------------------------
# Diagnosis effectiveness — wrong-diagnosis branch
# ---------------------------------------------------------------------------

DIAGNOSIS_WRONG_FLOOR: float = 0.05
"""Minimum effectiveness of wrong-diagnosis treatment.

Empirical tuning for the synthetic simulator: 5% floor reflects the
observation that even wrong-diagnosis therapy sometimes produces
partial effects (broad-spectrum antibiotics still cover some
pathogens; supportive care always helps)."""

DIAGNOSIS_WRONG_BASE: float = 0.2
"""Base effectiveness of wrong-diagnosis treatment at
``diagnostic_difficulty = 0``."""

DIAGNOSIS_WRONG_DIFFICULTY_SCALE: float = 0.1
"""Reduction in wrong-diagnosis effectiveness per unit of
``diagnostic_difficulty``.

Effectiveness = ``max(0.05, 0.2 - difficulty * 0.1)``, so a max-
difficulty wrong diagnosis drops to the 5% floor."""


# ---------------------------------------------------------------------------
# Diagnosis modifier gating
# ---------------------------------------------------------------------------

DIAGNOSIS_FULL_EFFECTIVE_THRESHOLD: float = 0.99
"""Effectiveness at or above which the ``apply_diagnosis_modifier``
short-circuits without dampening — no meaningful dampening required
for effectively-full treatment."""


# ---------------------------------------------------------------------------
# Natural recovery — severity-scaled baseline (immune + volume + anemia)
# ---------------------------------------------------------------------------

NATURAL_RECOVERY_SEVERITY_MILD: float = 1.2
"""Severity-scaling multiplier for ``"mild"`` presentations —
recovers faster than the moderate baseline."""

NATURAL_RECOVERY_SEVERITY_MODERATE: float = 1.0
"""Severity-scaling multiplier for ``"moderate"`` presentations
(baseline)."""

NATURAL_RECOVERY_SEVERITY_SEVERE: float = 0.6
"""Severity-scaling multiplier for ``"severe"`` presentations —
recovers more slowly than moderate."""

NATURAL_RECOVERY_SEVERITY_MULT_FALLBACK: float = 1.0
"""Fallback multiplier applied when the severity label is not one of
the three above (defaults to moderate)."""

NATURAL_RECOVERY_BASE_RATE: float = 0.01
"""Base inflammation-recovery rate per day (state-var units,
independent of severity and immune strength) at
``immune_reactivity = 1.0`` — modulated by both."""

NATURAL_RECOVERY_MID_MIN_DAY: int = 7
"""Post-admission day above which the natural recovery rate starts
decaying (acute-phase response fades)."""

NATURAL_RECOVERY_MID_DECAY_FACTOR: float = 0.7
"""Multiplier applied to the natural-recovery base rate for
``day > NATURAL_RECOVERY_MID_MIN_DAY``."""

NATURAL_RECOVERY_LATE_MIN_DAY: int = 14
"""Post-admission day above which the natural recovery rate decays
further (chronic-phase healing is slower still)."""

NATURAL_RECOVERY_LATE_DECAY_FACTOR: float = 0.5
"""Multiplier applied to the natural-recovery base rate for
``day > NATURAL_RECOVERY_LATE_MIN_DAY`` (compounded with the mid
decay)."""

VOLUME_RECOVERY_RATE_PER_UNIT_SEVERITY: float = 0.005
"""Daily volume-status renormalization rate (toward 0) at
``severity_scale = 1.0``.

Empirical tuning for the synthetic simulator: 0.005/day gives a
gentle drift toward euvolemia that matches the observed post-fluid-
resuscitation timeline."""


# ---------------------------------------------------------------------------
# Anemia recovery — bone marrow erythropoiesis
# ---------------------------------------------------------------------------

ANEMIA_RECOVERY_BASE_RATE: float = 0.015
"""Anemia-recovery rate on PODs 0-2 at ``severity_scale = 1.0``
(state-var units per day).

Empirical tuning for the synthetic simulator: 0.015/day is below the
peak reticulocyte-response rate — the first few days of an anemic
episode see limited bone-marrow output."""

ANEMIA_RECOVERY_ACCEL_MIN_DAY: int = 3
"""Post-admission day at or above which the anemia-recovery rate
accelerates (reticulocyte response peaks days 3-5)."""

ANEMIA_RECOVERY_ACCEL_RATE: float = 0.025
"""Anemia-recovery rate on PODs 3-6 at ``severity_scale = 1.0`` —
peak reticulocyte-response window."""

ANEMIA_RECOVERY_STEADY_MIN_DAY: int = 7
"""Post-admission day at or above which the anemia-recovery rate
settles to steady-state erythropoiesis."""

ANEMIA_RECOVERY_STEADY_RATE: float = 0.02
"""Anemia-recovery rate on PODs 7+ at ``severity_scale = 1.0`` —
sustained-production rate (~1 g/dL Hgb/week)."""
