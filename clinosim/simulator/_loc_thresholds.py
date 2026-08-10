"""AVPU consciousness-level (Level of Consciousness) inference thresholds (Issue #637).

``clinosim/simulator/vitals_pipeline.py::_loc_for`` infers a discrete
AVPU consciousness level (Alert / Verbal / Pain / Unresponsive) from
the patient's perfusion status, disease context, and length of stay.
The dispatch is a cascading if-chain: severe perfusion drop → likely
U/P, moderate → V/P, mild in a neuro cohort → V/A, and early days of
a neuro-monitored disease → A/V/P weighted sample.

Every scalar the function previously carried inline is lifted here per
policy §5. The perfusion cutoffs are cross-referenced to the sepsis
protocol (``sepsis.yaml``) and the neuro-monitoring day window
(2 days post-admission).

Byte-diff verification: swapping the inline literals for these named
constants MUST NOT change any RNG-consuming call. ``rng.random`` /
``rng.choice`` consume identical bytes whether their arguments come
from literals or module-scope constants.
"""

from __future__ import annotations

__all__ = [
    "LOC_MODERATE_HYPOPERFUSION_THRESHOLD",
    "LOC_MODERATE_V_OVER_P_PROBABILITY",
    "LOC_NEURO_EARLY_DAY_MAX",
    "LOC_NEURO_EARLY_WEIGHTS_AVP",
    "LOC_NEURO_MILD_HYPOPERFUSION_THRESHOLD",
    "LOC_NEURO_MILD_V_OVER_A_PROBABILITY",
    "LOC_REFRACTORY_SHOCK_THRESHOLD",
    "LOC_REFRACTORY_U_OVER_P_PROBABILITY",
]


# ---------------------------------------------------------------------------
# Refractory shock — most impaired consciousness band
# ---------------------------------------------------------------------------

LOC_REFRACTORY_SHOCK_THRESHOLD: float = 0.2
"""``perfusion_status`` strictly below which the patient is in
refractory shock — sampled as either "U"nresponsive or "P"ain.

Cross-reference: matches the ``sepsis.yaml`` severe-septic-shock
complication threshold (``perfusion_status < 0.2``). Also covers
severe neuro insult presentations."""

LOC_REFRACTORY_U_OVER_P_PROBABILITY: float = 0.5
"""Probability of sampling "U"nresponsive (vs. "P"ain response) when
in the refractory-shock band.

Empirical tuning for the synthetic simulator: 50/50 split reflects the
observation that at extreme perfusion collapse, patients are near-
equally likely to have lost pain response entirely."""


# ---------------------------------------------------------------------------
# Moderate hypoperfusion — V/P band
# ---------------------------------------------------------------------------

LOC_MODERATE_HYPOPERFUSION_THRESHOLD: float = 0.4
"""``perfusion_status`` strictly below which the patient responds only
to voice ("V") or pain ("P"), not spontaneously alert."""

LOC_MODERATE_V_OVER_P_PROBABILITY: float = 0.7
"""Probability of sampling "V"erbal (vs. "P"ain response) in the
moderate-hypoperfusion band.

Empirical tuning for the synthetic simulator: 70% verbal-responsive
reflects the observation that moderate hypoperfusion typically
preserves at least verbal-command response before dropping to pain-
only response."""


# ---------------------------------------------------------------------------
# Mild hypoperfusion in a neuro cohort — V/A band
# ---------------------------------------------------------------------------

LOC_NEURO_MILD_HYPOPERFUSION_THRESHOLD: float = 0.6
"""``perfusion_status`` strictly below which patients with neuro-
monitored diseases may drop from "A"lert to "V"erbal.

Empirical tuning for the synthetic simulator: 0.6 is above the
moderate-hypoperfusion threshold and marks the boundary at which
patients with a pre-existing neuro insult may become drowsy while
non-neuro patients would still be fully alert."""

LOC_NEURO_MILD_V_OVER_A_PROBABILITY: float = 0.5
"""Probability of sampling "V"erbal (vs. "A"lert) in the mild-
hypoperfusion band with a neuro disease.

Empirical tuning for the synthetic simulator: 50/50 split reflects
the day-to-day fluctuation seen in neuro patients — some days alert,
some days drowsy — with any given assessment landing on either."""


# ---------------------------------------------------------------------------
# Early post-admission neuro monitoring — A/V/P weighted sample
# ---------------------------------------------------------------------------

LOC_NEURO_EARLY_DAY_MAX: int = 2
"""Maximum day (inclusive) post-admission at which the neuro-monitored
disease cohort undergoes the weighted A/V/P sampling — beyond this
day, they default back to "A"lert unless perfusion drops.

Empirical tuning for the synthetic simulator: 2 days matches the
neuro-monitoring window used elsewhere in the pipeline (see
``NEURO_LOC_MONITORING_DISEASES``), reflecting the immediate post-
admission observation period for hemorrhagic stroke / subdural
hematoma etc."""

LOC_NEURO_EARLY_WEIGHTS_AVP: tuple[float, float, float] = (0.4, 0.4, 0.2)
"""Sampling weights for ("A", "V", "P") during the early post-
admission neuro-monitoring window.

Empirical tuning for the synthetic simulator: (40%, 40%, 20%) reflects
the observation that early neuro patients are often either alert or
verbally responsive, with a smaller fraction dropping to pain-only
response."""
