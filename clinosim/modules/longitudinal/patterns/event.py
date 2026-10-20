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
from pydantic import BaseModel, ConfigDict, Field


class EventResult(NamedTuple):
    """Outcome of one event step. ``fired=False`` leaves med/complication lists empty."""

    fired: bool
    emits_icd: str
    med_additions: list[str]
    med_removals: list[str]


_OPERATORS = {
    ">": _op.gt,
    "<": _op.lt,
    ">=": _op.ge,
    "<=": _op.le,
    "==": _op.eq,
    "!=": _op.ne,
}


class RateModifierWhen(BaseModel):
    """Trigger clause for a rate modifier. Phase 3 ships ``attribute`` triggers only."""

    model_config = ConfigDict(extra="forbid")

    attribute: str
    operator: str
    value: float

    def model_post_init(self, _ctx: Any) -> None:
        if self.operator not in _OPERATORS:
            raise ValueError(f"RateModifier.when.operator {self.operator!r} not in {sorted(_OPERATORS)}")


class RateModifier(BaseModel):
    """One multiplicative factor on an event's base annual rate."""

    model_config = ConfigDict(extra="forbid")

    when: RateModifierWhen
    factor: float = Field(..., ge=0.0)


class EventSpec(BaseModel):
    """Parameters for a one-shot ICD-onset or med-emitting event attribute."""

    model_config = ConfigDict(extra="forbid")

    event_name: str
    emits_icd: str
    emits_meds: list[str] = Field(default_factory=list)
    fire_marker: str = ""
    base_annual_rate: float = Field(..., ge=0.0, le=1.0)
    rate_modifiers: list[RateModifier] = Field(default_factory=list)
    one_shot: bool = True

    def model_post_init(self, _ctx: Any) -> None:
        if self.emits_icd == "" and not self.emits_meds:
            raise ValueError(f"EventSpec {self.event_name!r}: emits_icd and emits_meds cannot both be empty")


def _modifier_matches(modifier: RateModifier, context: dict[str, Any]) -> bool:
    """Evaluate one ``when:`` trigger against ``context``.

    Phase 3 ships ``attribute`` triggers only. An ``attribute`` whose
    name is absent from ``context["continuous"]`` returns False (no-op) —
    e.g. a non-DM person running against a yaml with an hba1c modifier.
    Unknown operator strings raise at EventSpec validation time (not here).
    """
    continuous = (context or {}).get("continuous") or {}
    if modifier.when.attribute not in continuous:
        return False
    op_fn = _OPERATORS.get(modifier.when.operator)
    if op_fn is None:  # pragma: no cover — EventSpec validation catches this earlier
        return False
    return bool(op_fn(float(continuous[modifier.when.attribute]), float(modifier.when.value)))


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
        # ICD-emitting event: dedup against chronic_conditions + prior new_complications.
        if spec.emits_icd and spec.emits_icd in person_chronic:
            return EventResult(False, spec.emits_icd, [], [])
        if spec.emits_icd:
            for snap in prev_history or []:
                if spec.emits_icd in getattr(snap, "new_complications", []):
                    return EventResult(False, spec.emits_icd, [], [])
        # Med-emitting event: dedup against prior med_additions via fire_marker.
        if spec.fire_marker:
            for snap in prev_history or []:
                if spec.fire_marker in getattr(snap, "med_additions", []):
                    return EventResult(False, spec.emits_icd, [], [])
    rate = float(spec.base_annual_rate)
    for modifier in spec.rate_modifiers:
        if _modifier_matches(modifier, context or {}):
            rate *= float(modifier.factor)
    rate = min(1.0, max(0.0, rate))
    fired = float(rng.random()) < rate
    if fired:
        return EventResult(True, spec.emits_icd, list(spec.emits_meds), [])
    return EventResult(False, spec.emits_icd, [], [])
