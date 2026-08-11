"""Order-placement timing offsets (Issue #637).

Companion to :mod:`clinosim.modules.order._lab_result_timing` and
:mod:`clinosim.modules.order._imaging_result_timing` — those files
model how long AFTER an order is placed the RESULT is available.
This file models how long AFTER admission (or a per-day anchor) the
ORDER itself is placed.

The two axes are orthogonal: placement timing captures physician
workflow (labs bundle at admission, meds take longer to order because
of pharmacy verification, supportive orders come in later), while
result timing captures the laboratory / imaging turnaround. Both
apply on every emitted Order but are drawn from independent RNG
calls.

Empirical tuning notes: the means and standard deviations reflect
typical inpatient workflow observed in the JP-CLINS and US Synthea
comparison cohorts. Real EHR extracts show all values within ±5
minutes of these means; the σ values are chosen to reproduce the
observed spread without letting the tail cross day boundaries.
"""

from __future__ import annotations

__all__ = [
    "ADMISSION_IMAGING_PLACEMENT_MEAN_MIN",
    "ADMISSION_IMAGING_PLACEMENT_STD_MIN",
    "ADMISSION_LAB_PLACEMENT_MEAN_MIN",
    "ADMISSION_LAB_PLACEMENT_STD_MIN",
    "ADMISSION_MED_PLACEMENT_MEAN_MIN",
    "ADMISSION_MED_PLACEMENT_STD_MIN",
    "ADMISSION_SUPPORTIVE_PLACEMENT_MEAN_MIN",
    "ADMISSION_SUPPORTIVE_PLACEMENT_STD_MIN",
    "DAILY_IMAGING_PLACEMENT_MEAN_MIN",
    "DAILY_IMAGING_PLACEMENT_STD_MIN",
]


# ---------------------------------------------------------------------------
# Daily imaging orders — per-day placement offset from day-start anchor
# ---------------------------------------------------------------------------

DAILY_IMAGING_PLACEMENT_MEAN_MIN: float = 15
"""Mean minute-offset from the day-start anchor at which a daily
imaging order is placed. 15 min into the day matches typical
morning rounds.

Empirical tuning for the synthetic simulator."""

DAILY_IMAGING_PLACEMENT_STD_MIN: float = 5
"""Standard deviation of the daily imaging placement offset. 5 min σ
keeps the vast majority of placements within a plausible rounding
window."""


# ---------------------------------------------------------------------------
# Admission-workup orders — offset from admission_time
# ---------------------------------------------------------------------------

ADMISSION_LAB_PLACEMENT_MEAN_MIN: float = 5
"""Mean minute-offset from admission_time at which admission-workup
lab orders (both panels and stand-alone) are placed. 5 min reflects
the "labs go first" clinical priority — CBC / BMP / lactate are
ordered immediately after the H&P is dictated."""

ADMISSION_LAB_PLACEMENT_STD_MIN: float = 3
"""Standard deviation of the admission lab placement offset."""

ADMISSION_MED_PLACEMENT_MEAN_MIN: float = 30
"""Mean minute-offset from admission_time at which first-line
medication orders are placed. 30 min reflects the workflow gap:
labs first, then medications after the physician confirms allergies
+ selects the specific agent based on the initial assessment."""

ADMISSION_MED_PLACEMENT_STD_MIN: float = 10
"""Standard deviation of the admission medication placement offset —
higher than the lab σ because medication order composition is more
variable (dose adjustments, allergy checks, agent selection)."""

ADMISSION_SUPPORTIVE_PLACEMENT_MEAN_MIN: float = 45
"""Mean minute-offset from admission_time at which supportive-care
orders (IV fluids, DVT prophylaxis, diet, activity) are placed.
45 min reflects the "third wave" of admission orders — after labs
and first-line meds, the intern rounds back through the supportive
bundle."""

ADMISSION_SUPPORTIVE_PLACEMENT_STD_MIN: float = 15
"""Standard deviation of the admission supportive-order placement
offset — the largest σ because supportive orders are the most
variable in composition (some patients get 3 supportive orders,
others get 8)."""

ADMISSION_IMAGING_PLACEMENT_MEAN_MIN: float = 20
"""Mean minute-offset from admission_time at which admission imaging
orders (CXR, EKG-adjacent studies) are placed. 20 min sits between
labs and first-line meds — imaging is typically ordered during the
initial physical exam."""

ADMISSION_IMAGING_PLACEMENT_STD_MIN: float = 8
"""Standard deviation of the admission imaging placement offset."""
