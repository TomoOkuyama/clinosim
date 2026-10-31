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


def _chronic_codes(chronic: Any) -> set[str]:
    """Normalise a chronic-conditions container to a set of ICD code
    strings. Accepts either bare ``str`` entries (the shape
    ``PersonRecord.chronic_conditions`` carries) or ``ChronicCondition``-
    shaped objects with a ``.code`` attribute (the shape
    ``PatientProfile.chronic_conditions`` carries). Issue #1757: the
    one_shot dedup and the ``has_chronic`` rate-modifier matcher must
    accept both shapes so that a caller passing the Patient-side view by
    mistake, or a mixed list, cannot silently bypass the self-ICD guard.
    """
    out: set[str] = set()
    for entry in chronic or ():
        if entry is None:
            continue
        code = getattr(entry, "code", None)
        if code:
            out.add(str(code))
        else:
            out.add(str(entry))
    return out


class RateModifierWhen(BaseModel):
    """Trigger clause for a rate modifier.

    Three mutually exclusive trigger shapes, exactly one must be populated:
    * ``attribute + operator + value`` — same-year AR(1) latent threshold
      (Phase 3). Fires when ``continuous[attribute] <op> value``.
    * ``has_chronic`` — any-of-list EXACT membership check on the person's
      ``chronic_conditions`` (Phase 4b.2.α). Fires when the person
      carries ANY of the listed ICD codes verbatim.
    * ``has_chronic_prefix`` — any-of-list STARTSWITH check on the
      person's ``chronic_conditions`` (Phase 4b.2.β). Fires when any of
      the person's codes starts with any listed prefix (e.g. ``["C"]``
      matches any cancer family; ``["I69"]`` matches every stroke
      sequela sub-code). Mirrors the retired Python helper
      ``_mental_health_onset_multiplier``'s ``requires_any_chronic_prefix``.
    """

    model_config = ConfigDict(extra="forbid")

    attribute: str | None = None
    operator: str | None = None
    value: float | None = None
    has_chronic: list[str] = Field(default_factory=list)
    has_chronic_prefix: list[str] = Field(default_factory=list)

    def model_post_init(self, _ctx: Any) -> None:
        has_attribute_trigger = self.attribute is not None and self.operator is not None and self.value is not None
        has_chronic_trigger = bool(self.has_chronic)
        has_prefix_trigger = bool(self.has_chronic_prefix)
        populated = sum((has_attribute_trigger, has_chronic_trigger, has_prefix_trigger))
        if populated != 1:
            raise ValueError(
                "RateModifierWhen requires exactly one of "
                "(attribute + operator + value), has_chronic, or has_chronic_prefix"
            )
        if has_attribute_trigger and self.operator not in _OPERATORS:
            raise ValueError(f"RateModifier.when.operator {self.operator!r} not in {sorted(_OPERATORS)}")


class RateModifier(BaseModel):
    """One multiplicative factor on an event's base annual rate."""

    model_config = ConfigDict(extra="forbid")

    when: RateModifierWhen
    factor: float = Field(..., ge=0.0)


class AgeBandRate(BaseModel):
    """One per-age-band Bernoulli rate (Phase 4b.2.α).

    Used by events whose base annual rate varies by age — e.g. chronic
    onset incidence that climbs from ``[18, 44]: 0.001`` to
    ``[65, 120]: 0.015``. The band is inclusive at both ends; age
    outside every band yields rate 0 (no fire).
    """

    model_config = ConfigDict(extra="forbid")

    age_lo: int = Field(..., ge=0)
    age_hi: int = Field(..., ge=0)
    rate: float = Field(..., ge=0.0, le=1.0)

    def model_post_init(self, _ctx: Any) -> None:
        if self.age_hi < self.age_lo:
            raise ValueError(f"AgeBandRate: age_hi {self.age_hi} < age_lo {self.age_lo}")


class EventSpec(BaseModel):
    """Parameters for a one-shot ICD-onset or med-emitting event attribute.

    #1754 added ``removes_meds``: a parallel list of drug names that are
    retracted from ``person.current_medications`` when the event fires.
    Used by substitution events (statin-intensity switch, pregnancy HTN
    swap, etc.) so a therapeutic substitution does not stack with the
    baseline agent. Empty by default — purely additive events (new ICD
    with its own base regimen, PRN rescue, …) remain unchanged.
    """

    model_config = ConfigDict(extra="forbid")

    event_name: str
    emits_icd: str
    emits_meds: list[str] = Field(default_factory=list)
    removes_meds: list[str] = Field(default_factory=list)
    fire_marker: str = ""
    base_annual_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    base_rate_by_age_band: list[AgeBandRate] = Field(default_factory=list)
    rate_modifiers: list[RateModifier] = Field(default_factory=list)
    one_shot: bool = True
    # Issue #2140: draw from a per-(person, year, event) sub-RNG instead of
    # the shared ``year_rng``, so adding the event shifts no other event's
    # draw for the same person-year.
    rng_isolated: bool = False

    def model_post_init(self, _ctx: Any) -> None:
        if self.emits_icd == "" and not self.emits_meds:
            raise ValueError(f"EventSpec {self.event_name!r}: emits_icd and emits_meds cannot both be empty")
        # Issue #2292: drugs are referenced by catalog drug_id and stored as
        # the catalog English name, which is what HomeMedication.drug_name
        # carries; an unknown drug fails here, at load.
        from clinosim.codes.drugs import find_drug

        for field_name in ("emits_meds", "removes_meds"):
            names: list[str] = []
            for ref in getattr(self, field_name):
                rec = find_drug(ref)
                if rec is None:
                    raise ValueError(f"EventSpec {self.event_name!r}: {field_name} {ref!r} is not in the drug catalog")
                names.append(rec.names.get("en", "") or ref)
            setattr(self, field_name, names)
        # base_annual_rate=0.0 with no band is a legitimate "zero-fire"
        # shape (e.g. a med-emitting event parked at 0 for activation-sampling
        # purposes). The resolution precedence is: band + age-in-context first,
        # then scalar base_annual_rate.


def _modifier_matches(modifier: RateModifier, context: dict[str, Any]) -> bool:
    """Evaluate one ``when:`` trigger against ``context``.

    Two trigger shapes (RateModifierWhen enforces exactly-one):
    * ``attribute`` triggers — same-year AR(1) latent threshold (Phase 3).
      An ``attribute`` absent from ``context["continuous"]`` returns
      False (no-op) — e.g. a non-DM person running against a yaml with
      an hba1c modifier.
    * ``has_chronic`` triggers (Phase 4b.2.α) — fire when the person
      carries ANY of the listed codes in ``context["chronic_conditions"]``.
      Absent context key is treated as empty list (no match).
    """
    when = modifier.when
    if when.has_chronic:
        chronic_set = _chronic_codes((context or {}).get("chronic_conditions"))
        return any(code in chronic_set for code in when.has_chronic)
    if when.has_chronic_prefix:
        chronic_set = _chronic_codes((context or {}).get("chronic_conditions"))
        return any(code.startswith(p) for code in chronic_set for p in when.has_chronic_prefix)
    # attribute trigger branch (validated: attribute/op/value all set).
    continuous = (context or {}).get("continuous") or {}
    if when.attribute not in continuous:
        return False
    op_fn = _OPERATORS.get(when.operator or "")
    if op_fn is None:  # pragma: no cover — EventSpec validation catches this earlier
        return False
    return bool(op_fn(float(continuous[when.attribute]), float(when.value or 0.0)))


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
        # Issue #1757: normalise via _chronic_codes so a ``ChronicCondition``-
        # shaped list element (``.code`` attribute) matches the bare-string
        # emits_icd — a plain ``in`` test would silently miss it.
        if spec.emits_icd:
            chronic_codes = _chronic_codes(person_chronic)
            if spec.emits_icd in chronic_codes:
                return EventResult(False, spec.emits_icd, [], [])
            for snap in prev_history or []:
                prior_complications = _chronic_codes(getattr(snap, "new_complications", []))
                if spec.emits_icd in prior_complications:
                    return EventResult(False, spec.emits_icd, [], [])
        # Med-emitting event: dedup against prior med_additions via fire_marker.
        if spec.fire_marker:
            for snap in prev_history or []:
                if spec.fire_marker in getattr(snap, "med_additions", []):
                    return EventResult(False, spec.emits_icd, [], [])
    rate = _resolve_base_rate(spec, context or {})
    for modifier in spec.rate_modifiers:
        if _modifier_matches(modifier, context or {}):
            rate *= float(modifier.factor)
    rate = min(1.0, max(0.0, rate))
    fired = float(rng.random()) < rate
    if fired:
        return EventResult(True, spec.emits_icd, list(spec.emits_meds), list(spec.removes_meds))
    return EventResult(False, spec.emits_icd, [], [])


def _resolve_base_rate(spec: EventSpec, context: dict[str, Any]) -> float:
    """Pick the base annual rate for this event-year.

    When ``base_rate_by_age_band`` is populated AND ``context["age"]``
    is present, the band whose ``[age_lo, age_hi]`` includes the age
    wins; age outside every band yields 0 (no fire). Otherwise falls
    through to the scalar ``base_annual_rate`` for backwards compat
    (Phase 3 / 4a / 4b.1 call sites).
    """
    if spec.base_rate_by_age_band and "age" in context:
        age = int(context["age"])
        for band in spec.base_rate_by_age_band:
            if band.age_lo <= age <= band.age_hi:
                return float(band.rate)
        return 0.0
    return float(spec.base_annual_rate)
