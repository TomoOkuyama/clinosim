"""AVPU consciousness-level (Level of Consciousness) inference thresholds (Issue #637).

``clinosim/simulator/vitals_pipeline.py::_loc_for`` infers a discrete
AVPU consciousness level (Alert / Verbal / Pain / Unresponsive) from
the ``consciousness_impairment`` state axis first (Issue #2058), then
the patient's perfusion status and disease context. The perfusion
dispatch is a cascading if-chain: severe perfusion drop → likely U/P,
moderate → V/P, mild in a neuro cohort → V/A.

Every scalar the function previously carried inline is lifted here per
policy §5. The perfusion cutoffs are cross-referenced to the sepsis
protocol (``sepsis.yaml``).

Byte-diff verification: swapping the inline literals for these named
constants MUST NOT change any RNG-consuming call. ``rng.random`` /
``rng.choice`` consume identical bytes whether their arguments come
from literals or module-scope constants.
"""

from __future__ import annotations

__all__ = [
    "LOC_MODERATE_HYPOPERFUSION_THRESHOLD",
    "LOC_MODERATE_V_OVER_P_PROBABILITY",
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
