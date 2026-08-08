"""Daily intake / output balance thresholds (Issue #561).

Values previously appeared as bare literals inside
``_generate_daily_io`` (``clinosim/simulator/vitals_pipeline.py``). They
describe the three IV-fluid regimens the nursing pipeline models plus the
anuria floor that guards the urine-output sampling.

Clinical citations:

- ``AGGRESSIVE_IV_ML`` / ``_SD`` — early-admission aggressive hydration
  (days 0–2). Mean 1500 mL/day with SD 300 approximates the WHO / SSCM
  sepsis-resuscitation range for a 70 kg adult inpatient (30 mL/kg first
  bolus, then maintenance). Not sepsis-specific in clinosim — the same
  regimen is used for any admission during the acute phase.
- ``DEHYDRATION_IV_ML`` / ``_SD`` — targeted rehydration when
  ``state.volume_status`` reads below :data:`DEHYDRATION_IV_TRIGGER`.
  Mean 1200 mL/day matches the KDIGO fluid-balance goal for patients with
  established mild-to-moderate dehydration without decompensated heart
  failure.
- ``MAINTENANCE_IV_ML`` / ``_SD`` — standard maintenance once the acute
  phase resolves (day ≥ 3 and hydration adequate). 4-2-1 rule for a
  euvolemic adult yields ~2000 mL/day of total fluid; this line captures
  only the IV portion (~500 mL) because most patients on maintenance IV
  are also drinking orally.
- ``ANURIA_FLOOR_ML`` (50 mL/day) — floor applied to sampled urine output.
  Below this the patient is effectively anuric; the floor prevents the
  random sampler from producing negative urine.
- ``DEHYDRATION_IV_TRIGGER`` (−0.2) — negative :attr:`volume_status`
  cutoff below which the dehydration IV regimen fires. This is ONE of
  three related dehydration thresholds in the codebase (see
  ``clinosim/modules/physiology/engine.py`` for −0.3 and −0.35 used by
  other rules); the divergence is intentional as of this extraction and
  is called out as follow-up in Issue #561.
"""

from __future__ import annotations

__all__ = [
    "AGGRESSIVE_IV_ML",
    "AGGRESSIVE_IV_SD",
    "ANURIA_FLOOR_ML",
    "DEHYDRATION_IV_ML",
    "DEHYDRATION_IV_SD",
    "DEHYDRATION_IV_TRIGGER",
    "MAINTENANCE_IV_ML",
    "MAINTENANCE_IV_SD",
]

AGGRESSIVE_IV_ML: int = 1500
"""Aggressive-hydration IV mean (mL/day) for the acute phase (days 0–2)."""

AGGRESSIVE_IV_SD: int = 300
"""Aggressive-hydration IV SD (mL/day)."""

DEHYDRATION_IV_ML: int = 1200
"""Dehydration-targeted IV mean (mL/day)."""

DEHYDRATION_IV_SD: int = 200
"""Dehydration-targeted IV SD (mL/day)."""

MAINTENANCE_IV_ML: int = 500
"""Maintenance IV mean (mL/day) for euvolemic patients past the acute phase."""

MAINTENANCE_IV_SD: int = 200
"""Maintenance IV SD (mL/day)."""

ANURIA_FLOOR_ML: int = 50
"""Anuria floor (mL/day) applied to sampled urine output."""

DEHYDRATION_IV_TRIGGER: float = -0.2
"""Volume-status cutoff below which the dehydration IV regimen fires
(see docstring for the intentional divergence from physiology-engine
thresholds)."""
