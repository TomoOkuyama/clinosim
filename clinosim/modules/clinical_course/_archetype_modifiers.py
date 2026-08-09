"""Archetype-probability and trajectory-progression modifiers (Issue #637).

The clinical-course engine shapes each patient's day-by-day physiologic
trajectory in three algorithmic stages:

1. **Archetype selection** — pick one of the course archetypes
   (``smooth_recovery`` / ``sudden_deterioration`` / …) via a weighted
   ``rng.choice``. The base weights come from either the disease-YAML
   ``course_archetypes`` block or the built-in ``_FALLBACK_PROBABILITIES``
   in ``engine.py``. Before the ``rng.choice`` fires, each severity
   category re-shapes the weights with a fixed set of multipliers — the
   :data:`SEVERITY_ARCHETYPE_MULTIPLIERS` block below.

2. **Age-based speed modulation** — recovery and deterioration deltas
   are stretched across more or fewer days depending on the patient's
   age band. The :data:`AGE_SPEED_FACTOR_BANDS` and
   :data:`AGE_SPEED_FACTORS` tables encode the age → speed-factor
   ladder as parallel constants.

3. **Amplitude / noise modulation** — trajectory deltas are scaled by
   patient-specific factors (immune reactivity for inflammation
   swings; treatment sensitivity for recovery magnitude; the
   deterioration amplifier for aging patients). The scalar constants
   in this stage live at the bottom of this module.

Every constant here is a scalar in ``[0.0, 3.0]`` or an age integer.
Byte-diff verification: swapping the inline literals for these named
constants MUST NOT change any numeric behaviour — every ``rng.choice``
receives the same ``p=`` vector and every arithmetic op the same
coefficient. Adding or shifting a modifier is a one-line dataclass /
tuple edit that fails loudly via the alignment check on the parallel
age-band tuples.

Reference for the multiplier / age-ladder shape: empirical tuning for
the synthetic simulator, calibrated to match the CIF-generation
audit's expected archetype-distribution + recovery-timing bands (no
single clinical guideline covers these exact ratios).
"""

from __future__ import annotations

__all__ = [
    "AGE_SPEED_FACTOR_BANDS",
    "AGE_SPEED_FACTORS",
    "AGED_DETERIORATION_AMPLIFIER_BASE",
    "IMMUNE_REACTIVITY_SCALE",
    "SEVERE_GRADUAL_DETERIORATION_MULT",
    "SEVERE_SMOOTH_RECOVERY_MULT",
    "SEVERE_SUDDEN_DETERIORATION_MULT",
    "MILD_GRADUAL_DETERIORATION_MULT",
    "MILD_SMOOTH_RECOVERY_MULT",
    "MILD_SUDDEN_DETERIORATION_MULT",
    "TRAJECTORY_NOISE_FLOOR",
    "TRAJECTORY_NOISE_PROP_SCALE",
]


# ---------------------------------------------------------------------------
# Stage 1: severity-based archetype-probability multipliers
# ---------------------------------------------------------------------------
#
# The base probability vector for each archetype (either from YAML or
# from _FALLBACK_PROBABILITIES) is multiplied by the constants below
# before normalization. Values > 1.0 promote the archetype for that
# severity band; values < 1.0 demote it.

SEVERE_GRADUAL_DETERIORATION_MULT: float = 2.0
"""Severe patients are 2× more likely to be assigned the
``gradual_deterioration`` archetype than the base probability suggests.
Empirical tuning: matches the CIF-audit expectation that severe
inpatients cluster in the "gets worse over the stay" band."""

SEVERE_SUDDEN_DETERIORATION_MULT: float = 2.0
"""Severe patients are 2× more likely to be assigned the
``sudden_deterioration`` archetype (paired with
:data:`SEVERE_GRADUAL_DETERIORATION_MULT` — both severe deterioration
modes double at once)."""

SEVERE_SMOOTH_RECOVERY_MULT: float = 0.6
"""Severe patients are ~40 % less likely to be assigned the
``smooth_recovery`` archetype. Empirical tuning to leave headroom for
the two deterioration modes to promote into."""

MILD_SMOOTH_RECOVERY_MULT: float = 1.3
"""Mild patients are ~30 % more likely to be assigned the
``smooth_recovery`` archetype. Empirical tuning."""

MILD_GRADUAL_DETERIORATION_MULT: float = 0.3
"""Mild patients are ~70 % less likely to be assigned the
``gradual_deterioration`` archetype. Empirical tuning: paired with
:data:`MILD_SUDDEN_DETERIORATION_MULT` to reflect that clinically-mild
patients almost never worsen."""

MILD_SUDDEN_DETERIORATION_MULT: float = 0.3
"""Mild patients are ~70 % less likely to be assigned the
``sudden_deterioration`` archetype. Empirical tuning."""


# ---------------------------------------------------------------------------
# Stage 2: age-based speed factors
# ---------------------------------------------------------------------------
#
# The ladder maps age → speed_factor. Recovery and deterioration deltas
# get scaled by speed_factor: > 1.0 = faster progression, < 1.0 =
# slower. Elderly patients recover slower (they get to the same
# clinical state over more days) but ALSO deteriorate slower in absolute
# terms — the deterioration amplifier below compensates for the second
# effect so aging patients still trend worse per unit time.
#
# ``AGE_SPEED_FACTOR_BANDS[i]`` is the upper bound of band ``i``; the
# corresponding ``AGE_SPEED_FACTORS[i]`` is applied when
# ``age < AGE_SPEED_FACTOR_BANDS[i]``. The final entry of
# ``AGE_SPEED_FACTORS`` is the default when no band matches (patients
# ≥ the last band's upper bound). Bands are half-open on the upper
# side, inclusive on the lower side.

AGE_SPEED_FACTOR_BANDS: tuple[int, ...] = (50, 70, 80, 90)
"""Upper-bound age (years, exclusive) for each speed-factor band.
Ordered ascending. Parallel to :data:`AGE_SPEED_FACTORS`."""

AGE_SPEED_FACTORS: tuple[float, ...] = (1.2, 1.0, 0.85, 0.7, 0.55)
"""Progression-speed factor per age band (parallel to
:data:`AGE_SPEED_FACTOR_BANDS`, plus a trailing default). Length is
``len(AGE_SPEED_FACTOR_BANDS) + 1``. Interpretation of each entry
(walking the bands from youngest to oldest):

- ``age < 50``  → 1.2 (fast; young patients recover briskly)
- ``age < 70``  → 1.0 (baseline)
- ``age < 80``  → 0.85 (mildly slowed)
- ``age < 90``  → 0.70 (elderly)
- ``age ≥ 90``  → 0.55 (nonagenarian, half-speed)

Empirical tuning for the synthetic simulator; the age brackets align
with the KDIGO / geriatric-syndrome literature grouping conventions."""


# Compile-time alignment check — fails on import if the tuples drift.
assert len(AGE_SPEED_FACTORS) == len(AGE_SPEED_FACTOR_BANDS) + 1, (
    "AGE_SPEED_FACTORS must have exactly one more entry than "
    "AGE_SPEED_FACTOR_BANDS (the trailing default). Got "
    f"len(factors)={len(AGE_SPEED_FACTORS)}, len(bands)={len(AGE_SPEED_FACTOR_BANDS)}."
)


# ---------------------------------------------------------------------------
# Stage 3: amplitude + noise modulation
# ---------------------------------------------------------------------------

IMMUNE_REACTIVITY_SCALE: float = 0.5
"""Divisor applied to ``profile.immune_reactivity`` when scaling
inflammation-level trajectory deltas.

``delta *= profile.immune_reactivity / IMMUNE_REACTIVITY_SCALE`` — a
patient at the population-median immune reactivity
(``immune_reactivity = 0.5``) gets ``× 1.0`` (no adjustment); a
hyperreactive patient (``0.75``) gets ``× 1.5`` bigger swings; a
hyporeactive patient (``0.25``) gets ``× 0.5``. Empirical tuning."""

AGED_DETERIORATION_AMPLIFIER_BASE: float = 2.0
"""Base value for the aged-deterioration amplifier
``AGED_DETERIORATION_AMPLIFIER_BASE - speed_factor``.

Applied to deterioration deltas (``delta < 0``) on
``renal_function`` / ``perfusion_status``. A young patient
(``speed_factor = 1.2``) gets ``× 0.8`` (slower deterioration than
baseline); an elderly patient (``speed_factor = 0.7``) gets ``× 1.3``
(faster deterioration). The linear form ``base - speed_factor`` keeps
the two modulations continuous: as recovery slows with age,
deterioration accelerates by the same amount."""

TRAJECTORY_NOISE_PROP_SCALE: float = 0.15
"""Proportional-noise scale on daily trajectory deltas.

``rng.normal(0, |delta| * TRAJECTORY_NOISE_PROP_SCALE + noise_floor)``
— larger swings carry proportionally larger biological variability.
The 0.15 coefficient produces a ~15 % coefficient of variation on
per-day deltas, matching published test-retest variability on the
underlying physiologic proxies."""

TRAJECTORY_NOISE_FLOOR: float = 0.002
"""Additive noise floor on daily trajectory deltas.

``rng.normal(0, |delta| * TRAJECTORY_NOISE_PROP_SCALE + TRAJECTORY_NOISE_FLOOR)``
— keeps the daily perturbation non-zero even when ``delta`` itself is
near zero (flat trajectory days still see mild biological noise from
activity / meals / stress)."""
