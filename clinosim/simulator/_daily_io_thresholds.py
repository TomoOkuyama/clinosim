"""Daily intake/output (IO) sampling thresholds (Issue #637).

``clinosim/simulator/vitals_pipeline.py::_generate_daily_io`` samples
oral intake and urine output for each hospital day. The IV-fluid
distributions and the anuria floor already live in
``clinosim.modules.observation.fluid_balance``; this file covers the
oral-intake distributions (day 0 NPO / poor appetite / recovering)
and the urine-output calculation constants that were still inline.

Byte-diff verification: swapping the inline literals for these named
constants MUST NOT change any RNG-consuming call. ``rng.normal``
consumes identical bytes whether its arguments come from literals or
module-scope constants.
"""

from __future__ import annotations

__all__ = [
    "IO_EARLY_DAY_THRESHOLD",
    "IO_ORAL_DAY0_MEAN_ML",
    "IO_ORAL_DAY0_STD_ML",
    "IO_ORAL_POOR_APPETITE_MEAN_ML",
    "IO_ORAL_POOR_APPETITE_STD_ML",
    "IO_ORAL_RECOVERING_MEAN_ML",
    "IO_ORAL_RECOVERING_STD_ML",
    "IO_POOR_APPETITE_INFLAMMATION_THRESHOLD",
    "IO_URINE_BASE_ML_PER_UNIT_RENAL",
    "IO_URINE_SD_FLOOR_ML",
    "IO_URINE_SD_RATIO",
]


# ---------------------------------------------------------------------------
# Early-day marker (used by both IV and oral branches)
# ---------------------------------------------------------------------------

IO_EARLY_DAY_THRESHOLD: int = 2
"""Post-admission day (inclusive) below which the "early days"
aggressive-hydration + NPO branches fire.

Empirical tuning for the synthetic simulator: PODs 0-2 capture the
acute-phase window where patients are typically NPO / minimal PO and
require aggressive IV fluid support before oral intake resumes."""


# ---------------------------------------------------------------------------
# Oral intake (mL per day) — three-branch distribution
# ---------------------------------------------------------------------------

IO_ORAL_DAY0_MEAN_ML: int = 200
"""Mean oral-intake (mL) on admission day 0.

Empirical tuning for the synthetic simulator: 200 mL reflects the
NPO / minimal-PO state on admission day — most patients are held nil
by mouth pending workup, or given only ice chips."""

IO_ORAL_DAY0_STD_ML: int = 100
"""Standard deviation of oral-intake (mL) on admission day 0."""

IO_POOR_APPETITE_INFLAMMATION_THRESHOLD: float = 0.3
"""``inflammation_level`` above which the patient is considered to
have poor appetite (post-admission-day 0).

Empirical tuning for the synthetic simulator: 0.3 approximates the
inflammation-level cutoff at which sepsis-adjacent / systemic-illness
appetite suppression becomes dominant, versus mild inflammation where
appetite is preserved."""

IO_ORAL_POOR_APPETITE_MEAN_ML: int = 500
"""Mean oral-intake (mL) when the patient has poor appetite (post-
admission-day 0 with elevated inflammation).

Empirical tuning for the synthetic simulator: 500 mL/day covers the
"clear liquids + small meals" regime typical of an acutely-ill
inpatient who is eating but not fully."""

IO_ORAL_POOR_APPETITE_STD_ML: int = 200
"""Standard deviation of oral-intake (mL) for the poor-appetite branch."""

IO_ORAL_RECOVERING_MEAN_ML: int = 1200
"""Mean oral-intake (mL) when the patient is recovering (past day 0,
inflammation below the poor-appetite threshold).

Empirical tuning for the synthetic simulator: 1200 mL/day approximates
the "full diet, adequate intake" oral fluid volume for a recovering
adult inpatient — includes meals, drinks, and between-meal fluids."""

IO_ORAL_RECOVERING_STD_ML: int = 300
"""Standard deviation of oral-intake (mL) for the recovering branch."""


# ---------------------------------------------------------------------------
# Urine output (mL per day) — proportional to renal function
# ---------------------------------------------------------------------------

IO_URINE_BASE_ML_PER_UNIT_RENAL: int = 1500
"""Base urine output (mL/day) at ``renal_function == 1.0``.

1500 mL/day approximates the healthy adult urine-output target
(~1-2 L/day given normal fluid intake). The output scales linearly
with ``renal_function`` — a renal_function of 0.5 gives base_urine of
750 mL/day, matching moderate CKD staging."""

IO_URINE_SD_RATIO: float = 0.2
"""Ratio of the urine-output standard deviation to the base output.

Empirical tuning for the synthetic simulator: 20% relative SD gives
plausible day-to-day variability in urine output while keeping ~68%
of samples within ±20% of the base — matches nursing-measured urine
volumes in real inpatient charts."""

IO_URINE_SD_FLOOR_ML: int = 100
"""Minimum SD (mL) for urine-output sampling.

Empirical tuning for the synthetic simulator: 100 mL floor prevents
the proportional SD from collapsing to near-zero at very low renal
function (where measurement noise would otherwise disappear entirely
— unrealistic given real urine-catch measurement precision)."""
