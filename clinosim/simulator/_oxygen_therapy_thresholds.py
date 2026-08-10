"""Oxygen therapy device selection thresholds (Issue #637).

``clinosim/simulator/vitals_pipeline.py::_o2_for`` dispatches an
oxygen-therapy device (nasal cannula / simple mask / non-rebreather)
based on the patient's SpO2 severity band. Each band samples a flow
rate from a bounded uniform distribution and picks the device from
a flow-based cutoff.

Every scalar the function previously carried inline is lifted here
per policy §5.

Byte-diff verification: swapping the inline literals for these named
constants MUST NOT change any RNG-consuming call. ``rng.uniform``
consumes identical bytes whether its arguments come from literals or
module-scope constants.
"""

from __future__ import annotations

__all__ = [
    "O2_MILD_FLOW_LPM_MAX",
    "O2_MILD_FLOW_LPM_MIN",
    "O2_MODERATE_FLOW_LPM_MAX",
    "O2_MODERATE_FLOW_LPM_MIN",
    "O2_NASAL_CANNULA_FLOW_MAX_LPM",
    "O2_NON_REBREATHER_FLOW_MIN_LPM",
    "O2_SEVERE_FLOW_LPM_MAX",
    "O2_SEVERE_FLOW_LPM_MIN",
]


# ---------------------------------------------------------------------------
# Severe hypoxemia (SpO2 < SPO2_SEVERE_HYPOXEMIA from vitals thresholds)
# ---------------------------------------------------------------------------

O2_SEVERE_FLOW_LPM_MIN: float = 6.0
"""Minimum oxygen flow (L/min) sampled for severe hypoxemia.

Empirical tuning for the synthetic simulator: 6 L/min is the lower
bound of the high-flow range used when nasal cannula is insufficient
— consistent with standard escalation from moderate to severe
hypoxia treatment."""

O2_SEVERE_FLOW_LPM_MAX: float = 10.0
"""Maximum oxygen flow (L/min) sampled for severe hypoxemia.

Empirical tuning for the synthetic simulator: 10 L/min is the upper
bound of the mask-based delivery range; higher flows require
non-rebreather with reservoir (still delivered via mask, up to 15
L/min max clinically)."""

O2_NON_REBREATHER_FLOW_MIN_LPM: float = 8.0
"""Flow rate (L/min) at or above which the device escalates from
simple mask to non-rebreather.

Empirical tuning for the synthetic simulator: 8 L/min is a
mid-range cutoff — a simple mask can effectively deliver 5-10 L/min,
but at ≥8 L/min a non-rebreather with reservoir is the more common
clinical choice to avoid rebreathing CO2 accumulation."""


# ---------------------------------------------------------------------------
# Moderate hypoxemia (SpO2 in [SPO2_SEVERE, SPO2_HYPOXEMIA_TRIGGER))
# ---------------------------------------------------------------------------

O2_MODERATE_FLOW_LPM_MIN: float = 2.0
"""Minimum oxygen flow (L/min) sampled for moderate hypoxemia.

Empirical tuning for the synthetic simulator: 2 L/min is the standard
starting nasal-cannula rate for supplemental oxygen."""

O2_MODERATE_FLOW_LPM_MAX: float = 5.0
"""Maximum oxygen flow (L/min) sampled for moderate hypoxemia.

Empirical tuning for the synthetic simulator: 5 L/min is the upper
limit of nasal-cannula comfort before switching to a mask; matches
the standard 1-6 L/min NC range clinicians use."""

O2_NASAL_CANNULA_FLOW_MAX_LPM: float = 4.0
"""Flow rate (L/min) at or below which the device stays as nasal
cannula rather than escalating to simple mask.

Empirical tuning for the synthetic simulator: 4 L/min is a
conservative NC comfort cutoff — patients requiring >4 L/min tend
to be more comfortable with a simple mask, especially in JP practice
where nasal-cannula humidification is less routine."""


# ---------------------------------------------------------------------------
# Mild / prophylactic supplemental oxygen (respiratory-condition
# patients who don't meet a specific hypoxemia threshold)
# ---------------------------------------------------------------------------

O2_MILD_FLOW_LPM_MIN: float = 1.0
"""Minimum oxygen flow (L/min) sampled for mild / prophylactic O2."""

O2_MILD_FLOW_LPM_MAX: float = 3.0
"""Maximum oxygen flow (L/min) sampled for mild / prophylactic O2.

Empirical tuning for the synthetic simulator: 1-3 L/min nasal cannula
is the standard "keep sats up" prophylactic supplementation for
respiratory patients who are borderline hypoxic — matches clinical
practice for post-op patients, mild COPD, or heart failure with
preserved SpO2."""
