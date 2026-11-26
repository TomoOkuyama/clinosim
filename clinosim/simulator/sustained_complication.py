"""A complication whose physiological effect is held while its cause lasts
(Issue #3827).

``state_impact`` of a complication is a one-time delta that the course then
recovers. Disseminated intravascular coagulation (DIC) is not a one-time
event: the consumption of platelets and clotting factors continues while the
systemic inflammation that drives it lasts, and fades as that inflammation
resolves. A complication entry may therefore declare ``sustained_state``::

    sustained_state:
      coagulation_status: {level: 0.85, driver: inflammation_level, release_below: 0.3, full_days: 3}

The held amount of each variable is ``level`` for ``full_days`` days from the
onset, then follows the driver: ``level`` while the driver is at its onset
value, falling linearly to zero as the driver falls to
``release_below``. The held amount is added to the state variable on top of
the course (as a delta, so the course's own recovery is kept), and is gone
once the driver is below ``release_below``. RNG-free.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from clinosim.modules.physiology.engine import apply_state_delta
from clinosim.types.clinical import PhysiologicalState

# The driver at onset is taken at least this far above ``release_below``, so
# a complication that fires while its driver is already near the release point
# still has a span to fall across.
_MIN_DRIVER_SPAN = 0.05


class SustainedEffectSpec(BaseModel):
    """One ``sustained_state`` entry of a complication."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    level: float = Field(gt=0.0, le=1.0)
    driver: str
    release_below: float = Field(ge=0.0, lt=1.0)
    full_days: int = Field(default=0, ge=0)


@dataclass
class SustainedHold:
    """The amount of one state variable currently held by a complication."""

    spec: SustainedEffectSpec
    reference: float  # the driver's value at onset
    held: float = 0.0
    days: int = 0  # advances since the onset


def sustained_specs(complication: dict[str, Any]) -> dict[str, SustainedEffectSpec]:
    """The validated ``sustained_state`` of a complication, by state variable."""
    return {
        var: SustainedEffectSpec.model_validate(raw) for var, raw in (complication.get("sustained_state") or {}).items()
    }


def start_holds(complication: dict[str, Any], state: PhysiologicalState) -> dict[str, SustainedHold]:
    """The holds a complication starts at its onset, by state variable."""
    holds: dict[str, SustainedHold] = {}
    for var, spec in sustained_specs(complication).items():
        reference = max(float(getattr(state, spec.driver)), spec.release_below + _MIN_DRIVER_SPAN)
        holds[var] = SustainedHold(spec=spec, reference=reference)
    return holds


def _target(hold: SustainedHold, driver_value: float) -> float:
    if hold.days <= hold.spec.full_days:
        return hold.spec.level
    span = hold.reference - hold.spec.release_below
    fraction = (driver_value - hold.spec.release_below) / span
    return hold.spec.level * min(1.0, max(0.0, fraction))


def advance_holds(state: PhysiologicalState, holds: dict[tuple[str, str], SustainedHold]) -> None:
    """Move every hold to the level its driver now implies and add the change to
    the state (clamped by the variable's range). A hold whose driver has fallen
    below its release point is dropped once it is back at zero."""
    for key in list(holds):
        hold = holds[key]
        hold.days += 1
        wanted = _target(hold, float(getattr(state, hold.spec.driver))) - hold.held
        before = float(getattr(state, key[1]))
        apply_state_delta(state, key[1], wanted)
        # Only what the state variable actually took (the range may cap it) can be taken back.
        hold.held += float(getattr(state, key[1])) - before
        if hold.held <= 0.0 and _target(hold, float(getattr(state, hold.spec.driver))) <= 0.0:
            del holds[key]
