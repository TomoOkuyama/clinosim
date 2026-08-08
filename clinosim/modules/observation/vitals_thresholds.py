"""Nursing vital-sign thresholds — fever detection and recheck cadence (Issue #561).

Clinical citations:

- ``FEVER_THRESHOLD_C`` (38.0 °C, ``100.4 °F``) — CDC / IDSA standard clinical
  definition of fever in an inpatient setting. Below this the vitals record
  reads as normothermic; at or above, the nursing note surfaces as "febrile".
- ``HIGH_FEVER_RECHECK_C`` (38.5 °C) — commonly used cutoff for provider
  notification and short-interval recheck (JCS / AHA analgesic and antipyretic
  protocol). At or above, nursing protocol pulls a recheck vitals reading
  within :data:`FEBRILE_RECHECK_WINDOW_MIN` minutes with probability
  :data:`FEBRILE_RECHECK_PROB` (models real-world documentation gaps —
  every-time recheck would over-state adherence).

All values were previously bare literals inside
``clinosim/simulator/vitals_pipeline.py``; extracted here so a clinician review
can adjust the cutoffs in one place with a code-level citation.
"""

from __future__ import annotations

__all__ = [
    "FEBRILE_RECHECK_PROB",
    "FEBRILE_RECHECK_WINDOW_MIN",
    "FEVER_THRESHOLD_C",
    "HIGH_FEVER_RECHECK_C",
]

FEVER_THRESHOLD_C: float = 38.0
"""Fever threshold (°C) — nursing note surfaces "febrile" at or above."""

HIGH_FEVER_RECHECK_C: float = 38.5
"""High-fever cutoff (°C) — triggers short-interval recheck at
:data:`FEBRILE_RECHECK_PROB` probability."""

FEBRILE_RECHECK_PROB: float = 0.7
"""Probability that a febrile recheck actually happens (models documentation
gap — 30% of high-fever patients do NOT get a recorded recheck in the
30–60-min window)."""

FEBRILE_RECHECK_WINDOW_MIN: tuple[int, int] = (30, 60)
"""Recheck window (min, max) in minutes when a recheck DOES fire — matches
standard nursing protocol for post-antipyretic monitoring."""
