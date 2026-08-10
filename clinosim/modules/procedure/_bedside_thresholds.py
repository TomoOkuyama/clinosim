"""Bedside / routine inpatient procedure thresholds (Issue #637).

``generate_bedside_procedures`` in ``clinosim/modules/procedure/engine.py``
fires each rule-matched procedure with a base probability that is scaled
by disease severity, then samples a post-admission time offset and
duration. The scaling multipliers, timing distribution parameters, and
duration bounds are lifted here per policy §5 so they are single-sourced
and independently documentable from the (large) rule table itself.

Byte-diff verification: swapping the inline literals for these named
constants MUST NOT change any RNG-consuming call. ``rng.exponential`` /
``rng.normal`` / ``rng.random`` all consume identical bytes whether the
mean/sd/probability arguments come from literals or module-scope
constants.
"""

from __future__ import annotations

__all__ = [
    "BEDSIDE_DURATION_MEAN_MIN",
    "BEDSIDE_DURATION_MIN_MIN",
    "BEDSIDE_DURATION_STD_MIN",
    "BEDSIDE_HOURS_OFFSET_EXPONENTIAL_MEAN",
    "BEDSIDE_HOURS_OFFSET_MIN",
    "BEDSIDE_SEVERITY_MODERATE_MULTIPLIER",
    "BEDSIDE_SEVERITY_MULTIPLIER_FALLBACK",
    "BEDSIDE_SEVERITY_MILD_MULTIPLIER",
    "BEDSIDE_SEVERITY_SEVERE_MULTIPLIER",
]


# ---------------------------------------------------------------------------
# Severity-based probability multipliers
# ---------------------------------------------------------------------------
# Each rule in ``_PROCEDURE_RULES`` carries a base probability tuned for a
# "moderate" inpatient. The multipliers below adjust that base for severity
# so a severe septic patient gets central-line placement much more reliably
# than a mild admission with the same base rule.

BEDSIDE_SEVERITY_SEVERE_MULTIPLIER: float = 1.3
"""Base-probability multiplier applied when the admission severity is
``severe``.

Empirical tuning for the synthetic simulator: 1.3× lifts moderate-rule
probabilities toward but not past 1.0 for procedures already very likely
in the moderate case (e.g. 0.80 → 1.04 → clamped 1.0), while giving
lower-probability procedures a meaningful bump. The 1.0 clamp lives in
the caller."""

BEDSIDE_SEVERITY_MODERATE_MULTIPLIER: float = 1.0
"""Base-probability multiplier applied when the admission severity is
``moderate``.

1.0 is the identity — rule probabilities are already tuned for the
moderate case, so no adjustment is needed."""

BEDSIDE_SEVERITY_MILD_MULTIPLIER: float = 0.5
"""Base-probability multiplier applied when the admission severity is
``mild``.

Empirical tuning for the synthetic simulator: 0.5× halves the rule
probabilities so mild admissions get roughly half the procedure burden
of a moderate admission — consistent with the clinical convention that
mild inpatients skip invasive lines / catheters that a moderate patient
would routinely receive."""

BEDSIDE_SEVERITY_MULTIPLIER_FALLBACK: float = 1.0
"""Multiplier used when the admission severity string is neither
``severe`` / ``moderate`` / ``mild``.

Falls back to the moderate multiplier (1.0) so an unrecognized severity
label produces a plausible default rather than dropping the procedure
entirely."""


# ---------------------------------------------------------------------------
# Post-admission timing offset
# ---------------------------------------------------------------------------

BEDSIDE_HOURS_OFFSET_MIN: float = 0.5
"""Minimum hours after admission at which a bedside procedure can be
scheduled.

Empirical tuning for the synthetic simulator: 0.5h (30 minutes) reflects
the shortest realistic wall-clock gap between admission order and
procedure completion — a rapid IV line placement in the ED, for
example. Prevents the exponential distribution's zero-lower-tail from
producing implausibly-simultaneous admission and procedure timestamps."""

BEDSIDE_HOURS_OFFSET_EXPONENTIAL_MEAN: float = 6.0
"""Mean (in hours) of the exponential distribution sampled for
post-admission bedside-procedure timing.

Empirical tuning for the synthetic simulator: a mean of 6h ≈ a median
of ~4.2h post-admission (exponential median = ln(2)·mean), matching the
convention that most bedside procedures (Foley, IV, NG tube) happen in
the first admission workshift with a long tail into the following day."""


# ---------------------------------------------------------------------------
# Procedure duration
# ---------------------------------------------------------------------------

BEDSIDE_DURATION_MIN_MIN: int = 10
"""Minimum duration (minutes) of a bedside procedure.

Empirical tuning for the synthetic simulator: 10 minutes is the
shortest realistic room-time for even the quickest bedside procedure
(e.g. simple wound care, IV line placement). Prevents the normal
distribution's left tail from producing negative or unrealistically
short durations."""

BEDSIDE_DURATION_MEAN_MIN: int = 30
"""Mean duration (minutes) of a bedside procedure sampled from
``rng.normal(mean, sd)``.

Empirical tuning for the synthetic simulator: 30 minutes is a broad
average across the ~20 bedside procedures in ``_BEDSIDE_PROCEDURES``,
which range from ~10 min (IV line) to ~60 min (bronchoscopy). A single
mean is a simplification — future work could per-procedure the
distribution — but it produces plausible aggregate room-utilization
numbers today."""

BEDSIDE_DURATION_STD_MIN: int = 10
"""Standard deviation (minutes) of the bedside-procedure duration
distribution.

Empirical tuning for the synthetic simulator: 10 minutes gives ~68% of
sampled durations in the [20, 40] range, which is a plausible spread
around the 30-minute mean."""
