"""Encounter-scheduling thresholds for the simulator top-level loop (Issue #637).

``clinosim/simulator/engine.py`` schedules three families of encounters
based on population events:

1. Outpatient chronic-follow-up / screening visits — scheduled at a
   fixed hour with a minute-jitter, with optional quarterly / annual
   lab additions per YAML follow-up spec.
2. ED-visit-not-admitted sampling — a rate-per-admitted multiplier
   determines the total ED-visit count, then each slot picks a
   condition weighted by occupation risk and a favored ED-arrival
   hour.

Every scalar the loop previously carried inline is lifted here per
policy §5. The health-screening default lab panel is *not* extracted
here — it is scenario-specific rather than a threshold and reads
better inline alongside the visit-dispatch context.

Byte-diff verification: swapping the inline literals for these named
constants MUST NOT change any RNG-consuming call. ``rng.integers`` /
``rng.random`` / ``rng.choice`` consume identical bytes whether the
arguments come from literals or module-scope constants.
"""

from __future__ import annotations

__all__ = [
    "ED_DAY_MAX_EXCLUSIVE",
    "ED_DAY_MIN",
    "ED_FAVORED_HOURS",
    "ED_MINUTE_JITTER_MAX_EXCLUSIVE",
    "ED_MINUTE_JITTER_MIN",
    "ED_OCCUPATION_MISMATCH_FALLBACK",
    "OUTPATIENT_CALENDAR_VISIT_HOUR",
    "OUTPATIENT_LABS_ANNUAL_PROBABILITY",
    "OUTPATIENT_LABS_QUARTERLY_PROBABILITY",
    "OUTPATIENT_MINUTE_JITTER_MAX_EXCLUSIVE",
    "OUTPATIENT_MINUTE_JITTER_MIN",
]


# ---------------------------------------------------------------------------
# Outpatient calendar (chronic follow-up + screening)
# ---------------------------------------------------------------------------

OUTPATIENT_CALENDAR_VISIT_HOUR: int = 10
"""Hour-of-day at which calendar-scheduled outpatient visits are
placed (before minute jitter).

10 AM matches the typical mid-morning outpatient clinic slot after
the early appointments have cleared."""

OUTPATIENT_MINUTE_JITTER_MIN: int = 0
"""Inclusive lower bound of the outpatient minute jitter passed to
``rng.integers``."""

OUTPATIENT_MINUTE_JITTER_MAX_EXCLUSIVE: int = 45
"""Exclusive upper bound of the outpatient minute jitter — samples
0-44 minutes past the base visit hour.

45 minutes keeps visits within the mid-morning-to-just-before-lunch
window, matching a realistic outpatient scheduling grid."""

OUTPATIENT_LABS_QUARTERLY_PROBABILITY: float = 0.25
"""Probability that a follow-up spec's ``labs_quarterly`` list adds a
lab to this visit's panel — approximates the "once per 4 visits"
quarterly cadence when visits are per-quarter."""

OUTPATIENT_LABS_ANNUAL_PROBABILITY: float = 0.08
"""Probability that a follow-up spec's ``labs_annual`` list adds a
lab to this visit's panel — approximates the "once per 12 visits"
annual cadence for less-frequent screening labs."""


# ---------------------------------------------------------------------------
# ED-visit-not-admitted sampling
# ---------------------------------------------------------------------------

ED_OCCUPATION_MISMATCH_FALLBACK: float = 0.0
"""Occupation-risk multiplier applied when an ED condition has an
occupation-risk table but the person's occupation is not in it.

Set to 0.0 — strict gate. Workplace-specific ED chief complaints
(``chemical_exposure``, ``crush_injury_hand``, ``industrial_burn_severe``,
``fall_from_height``, ``electrical_injury``, ``eye_foreign_body``) carry
"at workplace" / "work-related" text and are only coherent on
occupations whose workplace exposes the person to the hazard. For
occupations whose workplace is an office / school / home / retirement
(``office``, ``student``, ``retired``, ``unemployed``, ``homemaker``,
``preschool``, ``infant``, ``education``), the workplace-exposure
chief complaint is semantically a mis-fit — the person simply picks
one of the non-work-related ED CCs instead.

Audit s103 cohort finding: pre-fix a 5-sample pull surfaced an
``occupation=office`` patient carrying ``chief_complaint="Chemical
exposure at workplace"`` on an ED visit, which should not happen.
Issue #1702. The pre-fix fallback was 0.05 (5 % residual rate for all
workplace CCs across all occupations); setting it to 0.0 makes the
occupation whitelist in ``demographics.yaml::occupation_risk_multipliers``
authoritative.

Separate from :data:`OCCUPATION_MISMATCH_FALLBACK_MULTIPLIER` in
``_population_workflow_thresholds.py`` (0.2) — the monthly-events
disease incidence path keeps its soft fallback for non-ED-CC paths
where the semantic constraint is weaker."""

ED_DAY_MIN: int = 1
"""Inclusive lower bound of the ED-visit day sampled by
``rng.integers``."""

ED_DAY_MAX_EXCLUSIVE: int = 28
"""Exclusive upper bound of the ED-visit day (samples 1-27) — same
convention as the monthly-event day-jitter (February-safe cap)."""

ED_FAVORED_HOURS: tuple[int, int, int, int, int, int, int, int] = (9, 10, 14, 15, 19, 20, 21, 22)
"""Hour-of-day list favored for ED arrivals, sampled by ``rng.choice``.

Empirical tuning for the synthetic simulator: three peak bands —
mid-morning (9, 10), early-afternoon (14, 15), and evening (19-22).
Matches the well-documented US/JP ED-arrival bimodal distribution
(mid-morning post-primary-care-referral peak + evening peak when
outpatient clinics have closed)."""

ED_MINUTE_JITTER_MIN: int = 0
"""Inclusive lower bound of the ED-visit minute jitter (within the
sampled hour)."""

ED_MINUTE_JITTER_MAX_EXCLUSIVE: int = 60
"""Exclusive upper bound of the ED-visit minute jitter (0-59 minutes
past the sampled hour)."""
