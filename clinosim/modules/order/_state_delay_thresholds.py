"""Hospital-state-driven order-result delay thresholds (Issue #637).

``calculate_result_time_from_state`` in
``clinosim/modules/order/engine.py`` computes the result-return time
for lab and imaging orders when a live ``hospital_state`` object is
available — delays emerge from resource utilization and staffing
rather than the static distributions used by
``calculate_lab_result_time`` / ``calculate_imaging_result_time``.

The scalars this function multiplies onto the state-derived delay
(random jitter, floor, non-result trivial offset) are lifted here per
policy §5. Night-shift deferral constants are shared with the
lab-result timing family and imported from ``_lab_result_timing.py``
directly at the call site — this file only holds the constants unique
to the state-based path.

Byte-diff verification: swapping the inline literals for these named
constants MUST NOT change any RNG-consuming call. ``rng.normal``
consumes identical bytes whether its parameters come from literals or
module-scope constants.
"""

from __future__ import annotations

__all__ = [
    "NONRESULT_ORDER_TRIVIAL_OFFSET_MIN",
    "STATE_DELAY_FLOOR_MIN",
    "STATE_DELAY_JITTER_MEAN",
    "STATE_DELAY_JITTER_STD",
]


NONRESULT_ORDER_TRIVIAL_OFFSET_MIN: int = 5
"""Fixed minutes added to ``ordered_datetime`` when the order type
neither ``lab`` nor ``imaging`` (medication, diet, etc.) — such orders
have no lab-turnaround workflow, so the "result time" is a
placeholder-only trivial offset.

5 minutes matches the convention that a medication or diet order is
effectively acted on immediately upon signing; the small offset
ensures ``result_time > ordered_datetime`` so downstream chronology
sorts remain stable."""


STATE_DELAY_JITTER_MEAN: float = 0.0
"""Mean of the multiplicative jitter applied to the state-derived delay.

Zero-mean by design: the state model already produces the expected
delay, and this jitter only introduces random spread around it — a
non-zero mean would systematically shift delays away from the model's
prediction."""

STATE_DELAY_JITTER_STD: float = 0.2
"""Standard deviation of the multiplicative jitter (``1 + N(0, sd)``)
applied to the state-derived delay.

Empirical tuning for the synthetic simulator: sd = 0.2 gives ±20% one-
sigma spread — matches the observed order-to-result variance in real
hospital lab / imaging queues where two identical orders placed
minutes apart return within roughly 20% of each other's turnaround."""


STATE_DELAY_FLOOR_MIN: float = 10.0
"""Minimum result-return delay (minutes) after jitter is applied.

Empirical tuning for the synthetic simulator: 10 minutes prevents the
combination of a low state-derived delay and the left tail of the
jitter distribution from producing implausibly fast (or negative)
turnaround times. Even STAT orders on an idle resource have a
non-trivial pre-analytic / analytic minimum."""
