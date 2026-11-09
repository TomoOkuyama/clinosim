"""Constants of the medication-order supersede pass (Issue #2983)."""

from __future__ import annotations

__all__ = ["SWITCH_SLOT_WINDOW_MIN"]

SWITCH_SLOT_WINDOW_MIN: int = 60
"""Minutes before the replacing order's switch time within which a dose of
the replaced order counts as the same administration slot, so the new drug's
dose stands in for it and the old one is not charted. Unit: minutes.
Rationale: a switch is given at the time the old drug's next dose falls due
(IDSA/SHEA antimicrobial stewardship guidance: an escalated or de-escalated
beta-lactam replaces the previous agent, it is not added to it); MAR doses
of one slot are charted within an hour of each other, while the shortest
scheduled interval of the drugs superseded here is four hours."""
