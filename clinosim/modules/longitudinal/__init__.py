"""Longitudinal state-evolution subsystem for clinosim.

See ``docs/superpowers/specs/2026-10-20-longitudinal-state-evolution-design.md``
for the full design. Phase 1 (this release) lands the framework +
HbA1c AR(1) attribute. Phase 2 adds Markov transitions
(CKD / CCS / NYHA / CDR / GOLD); Phase 3 adds event firing
(DM complication onset, treatment escalation, BMI drift).
"""

from clinosim.modules.longitudinal.engine import (
    advance_one_year,
    initial_snapshot,
    state_at,
)
from clinosim.modules.longitudinal.snapshot import (
    YearSnapshot,
    yearsnapshot_from_dict,
)

__all__ = [
    "YearSnapshot",
    "advance_one_year",
    "initial_snapshot",
    "state_at",
    "yearsnapshot_from_dict",
]
