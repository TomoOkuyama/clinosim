"""Event one-shot ICD-onset pattern.

Third pattern of the longitudinal engine (§4.2.3 of the spec). An
event attribute fires at most once per patient (``one_shot: true``,
the Phase 3 default) and emits an ICD onto
``YearSnapshot.new_complications`` + ``person.chronic_conditions``
through the engine dispatch. Rate = ``base_annual_rate`` scaled by
each matching ``rate_modifiers`` factor, clamped to ``[0.0, 1.0]``.

Rate modifiers address a referenced attribute's current-year value in
``context["continuous"]`` (populated by the engine before dispatching
each event, so same-year AR(1) latents are visible). A modifier whose
referenced attribute is missing from the context is a no-op — not an
error, not a zero-multiplier — so a non-DM person with an HbA1c modifier
simply falls through to the base rate.

Spec: docs/superpowers/specs/2026-10-20-longitudinal-state-evolution-design.md §4.2.3
"""

from __future__ import annotations

import operator as _op
from typing import Any, NamedTuple

import numpy as np
from pydantic import BaseModel, Field


class EventResult(NamedTuple):
    """Outcome of one event step. ``fired=False`` leaves med/complication lists empty."""

    fired: bool
    emits_icd: str
    med_additions: list[str]
    med_removals: list[str]


class EventSpec(BaseModel):
    """Parameters for a one-shot ICD-onset event attribute."""

    event_name: str
    emits_icd: str
    base_annual_rate: float = Field(..., ge=0.0, le=1.0)
    rate_modifiers: list[dict[str, Any]] = Field(default_factory=list)
    one_shot: bool = True


_OPERATORS = {
    ">": _op.gt,
    "<": _op.lt,
    ">=": _op.ge,
    "<=": _op.le,
    "==": _op.eq,
    "!=": _op.ne,
}


def _modifier_matches(modifier: dict[str, Any], context: dict[str, Any]) -> bool:
    """Evaluate one ``when:`` trigger against ``context``.

    Phase 3 ships ``attribute`` triggers only. An ``attribute`` key whose
    name is absent from ``context["continuous"]`` returns False (no-op).
    """
    when = modifier.get("when") or {}
    attribute = when.get("attribute")
    if attribute is not None:
        continuous = (context or {}).get("continuous") or {}
        if attribute not in continuous:
            return False
        op_sym = when.get("operator")
        threshold = when.get("value")
        if op_sym not in _OPERATORS:
            return False
        return bool(_OPERATORS[op_sym](float(continuous[attribute]), float(threshold)))
    return False


def step(
    person_chronic: list[str],
    prev_history: list,
    rng: np.random.Generator,
    spec: EventSpec,
    *,
    context: dict[str, Any] | None = None,
) -> EventResult:
    """Decide whether the event fires this year.

    ``person_chronic`` is the person's current ``chronic_conditions`` list.
    ``prev_history`` is the person's ``longitudinal_history`` prior to the
    current year (used to enforce ``one_shot`` against re-fires in a
    later year). ``context`` carries ``{"continuous": {latent: value}}``
    where modifiers resolve.
    """
    if spec.one_shot:
        if spec.emits_icd in person_chronic:
            return EventResult(False, spec.emits_icd, [], [])
        for snap in prev_history or []:
            if spec.emits_icd in getattr(snap, "new_complications", []):
                return EventResult(False, spec.emits_icd, [], [])
    rate = float(spec.base_annual_rate)
    for modifier in spec.rate_modifiers:
        if _modifier_matches(modifier, context or {}):
            rate *= float(modifier.get("factor", 1.0))
    rate = min(1.0, max(0.0, rate))
    fired = float(rng.random()) < rate
    return EventResult(fired, spec.emits_icd, [], [])
