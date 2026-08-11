"""Nursing-score thresholds (Issue #637).

Lifts the previously-inline scalars from
:mod:`clinosim.modules.observation.nursing` into named constants. The
four scoring instruments (NEWS2, GCS, Braden, Morse) are already
data-driven through ``reference_data/nursing_scores.yaml`` for their
published band tables, but a handful of pre-clamp bounds, jitter
ranges, and internal-lookup cutoffs remained inline. Those live here
per policy §5.

Byte-diff verification: swapping the inline literals for these named
constants MUST NOT change any RNG-consuming call. ``rng.integers``
consumes identical bytes whether ``low`` / ``high`` come from
literals or module-scope constants.
"""

from __future__ import annotations

__all__ = [
    "AVPU_TO_BRADEN_SENSORY",
    "BARTHEL_DEFAULT",
    "BRADEN_FRICTION_BEDBOUND_MAX_EXCLUSIVE",
    "BRADEN_FRICTION_LIMITED_MAX_EXCLUSIVE",
    "BRADEN_MOISTURE_HIGH_THRESHOLD",
    "BRADEN_MOISTURE_LOW_THRESHOLD",
    "BRADEN_MOISTURE_MID_THRESHOLD",
    "BRADEN_NUTRITION_JITTER_LOW",
    "BRADEN_NUTRITION_JITTER_HIGH",
    "BRADEN_SCORE_MAX",
    "BRADEN_SCORE_MIN",
    "GCS_JITTER_HIGH",
    "GCS_JITTER_LOW",
    "GCS_PERFUSION_DECREMENT_SCALE",
    "MORSE_GAIT_IMPAIRED_MAX_EXCLUSIVE",
    "MORSE_GAIT_WEAK_MAX_EXCLUSIVE",
    "MORSE_HISTORY_AGE_THRESHOLD",
    "MORSE_JITTER_HIGH",
    "MORSE_JITTER_LOW",
    "MORSE_SCORE_MAX",
    "MORSE_SCORE_MIN",
    "NEWS2_SCORE_MAX",
    "NEWS2_SCORE_MIN",
]


# ---------------------------------------------------------------------------
# NEWS2 aggregate bounds
# ---------------------------------------------------------------------------

NEWS2_SCORE_MIN: int = 0
"""Lower clamp for the aggregated NEWS2 score. NEWS2 by definition
cannot go negative — the clamp catches any arithmetic underflow from
mis-configured band tables (fail-safe, published NEWS2 always
returns 0-20)."""

NEWS2_SCORE_MAX: int = 20
"""Upper clamp for the aggregated NEWS2 score. Sum of all published
NEWS2 subscale maxima at extreme derangement (respiratory + SpO2 +
oxygen + temperature + BP + HR + consciousness) — exceeding this
would indicate a YAML band-table bug."""


# ---------------------------------------------------------------------------
# GCS perfusion-linked adjustment + jitter
# ---------------------------------------------------------------------------

GCS_PERFUSION_DECREMENT_SCALE: float = 2.0
"""Multiplier applied to ``(1 - perfusion_status)`` to compute the
GCS decrement for shock / encephalopathy.

Empirical tuning for the synthetic simulator: 2.0 gives a
perfusion_status=0.5 patient a −1 decrement, and a
perfusion_status=0.0 patient a −2 decrement — a modest but non-zero
nudge that lets severely-shocked patients bias toward GCS 13-14
without collapsing to GCS < 8 (which would trigger cascading
critical-care logic)."""

GCS_JITTER_LOW: int = 0
"""Inclusive lower bound of the GCS jitter draw (``rng.integers``
with ``endpoint=True``)."""

GCS_JITTER_HIGH: int = 1
"""Inclusive upper bound of the GCS jitter draw. Combined with
:data:`GCS_JITTER_LOW` yields 0 or 1 — a small deterministic-per-
sub-seed nudge that avoids clumping GCS observations at exact
computed values."""


# ---------------------------------------------------------------------------
# Braden score internals
# ---------------------------------------------------------------------------

BARTHEL_DEFAULT: int = 100
"""Fallback Barthel ADL score when the ``adl`` dict is None or
missing ``barthel_score``. 100 = fully independent — a safe default
that biases toward under-treatment risk (over-treating an actually-
independent patient is more visible than under-treating an actually-
dependent one)."""

AVPU_TO_BRADEN_SENSORY: dict[str, int] = {"A": 4, "V": 3, "P": 2, "U": 1}
"""AVPU consciousness level → Braden sensory-perception subscale
(published range 1-4). Alert (A) is fully sensate; Unresponsive (U)
cannot detect pressure-related discomfort.

Kept as a dedicated table (not a formula) because the mapping is
1:1 with the published Braden scoring guide."""

BRADEN_MOISTURE_HIGH_THRESHOLD: float = 0.5
"""``volume_status`` cutoff above which Braden moisture subscale =
1 (constantly moist). Volume overload / edema / incontinence proxy.

Empirical tuning for the synthetic simulator: 0.5 flags the top
~15% of patients (severe volume overload) into the highest
moisture-risk band."""

BRADEN_MOISTURE_MID_THRESHOLD: float = 0.3
"""``volume_status`` cutoff above which Braden moisture subscale =
2 (very moist)."""

BRADEN_MOISTURE_LOW_THRESHOLD: float = 0.0
"""``volume_status`` cutoff above which Braden moisture subscale =
3 (occasionally moist). Zero or negative volume_status = subscale 4
(dry)."""

BRADEN_NUTRITION_JITTER_LOW: int = -1
"""Inclusive lower bound of Braden nutrition-subscale jitter — allows
the nutrition subscale to deviate ±1 from the activity subscale
(realistic patient variability)."""

BRADEN_NUTRITION_JITTER_HIGH: int = 1
"""Inclusive upper bound of Braden nutrition-subscale jitter."""

BRADEN_FRICTION_BEDBOUND_MAX_EXCLUSIVE: int = 25
"""Barthel cutoff below which Braden friction subscale = 1 (problem).
Barthel < 25 corresponds to full bed-bound status."""

BRADEN_FRICTION_LIMITED_MAX_EXCLUSIVE: int = 60
"""Barthel cutoff below which Braden friction subscale = 2 (potential
problem). Barthel 25-59 corresponds to partial mobility."""

BRADEN_SCORE_MIN: int = 6
"""Published minimum total Braden score (all 6 subscales at their
minimum value of 1). Total-score clamp."""

BRADEN_SCORE_MAX: int = 23
"""Published maximum total Braden score (all 6 subscales at their
maximum value)."""


# ---------------------------------------------------------------------------
# Morse Fall Scale internals
# ---------------------------------------------------------------------------

MORSE_HISTORY_AGE_THRESHOLD: int = 75
"""Age at or above which the Morse history-of-falling item fires
based on age alone. Approximates the published Morse guidance that
falls-history is high in the elderly (age is a proxy for
undocumented past falls)."""

MORSE_GAIT_IMPAIRED_MAX_EXCLUSIVE: int = 60
"""Barthel cutoff below which Morse gait item = ``gait_impaired``.
Matches the Braden friction cutoff — both express "significantly
limited mobility"."""

MORSE_GAIT_WEAK_MAX_EXCLUSIVE: int = 90
"""Barthel cutoff below which Morse gait item = ``gait_weak``.
Barthel 60-89 = weak but ambulatory."""

MORSE_JITTER_LOW: int = -5
"""Inclusive lower bound of Morse total-score jitter — realistic
observer variability around the computed score."""

MORSE_JITTER_HIGH: int = 5
"""Inclusive upper bound of Morse total-score jitter."""

MORSE_SCORE_MIN: int = 0
"""Lower clamp for total Morse score."""

MORSE_SCORE_MAX: int = 125
"""Upper clamp for total Morse score — matches the published Morse
Fall Scale ceiling."""
