"""Longitudinal engine entry points.

Three callables form the public surface:

- :func:`initial_snapshot` — build the sim-start ``YearSnapshot`` for a
  person. Appends to ``person.longitudinal_history`` and returns it.
- :func:`advance_one_year` — advance one year's state. Appends a new
  snapshot and returns it. Idempotent-raising on duplicate year;
  monotonic-raising on backward year.
- :func:`state_at` — pure lookup. Returns the ``YearSnapshot`` whose
  year matches the given point in time.

See the Phase 1 spec at
``docs/superpowers/specs/2026-10-20-longitudinal-state-evolution-design.md``
§5.1 for the API contract.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING, Callable

import numpy as np

from clinosim.modules.longitudinal.loader import (
    AttributeSpec,
    load_attribute_specs,
    topological_order,
)
from clinosim.modules.longitudinal.patterns import PATTERN_REGISTRY
from clinosim.modules.longitudinal.snapshot import YearSnapshot

if TYPE_CHECKING:
    from clinosim.types.population import PersonRecord


def _chronic_codes_match(person_codes: list[str], required_prefixes: list[str]) -> bool:
    """A required prefix matches when any person-code starts with it.
    An empty requirement list is satisfied by every person."""
    if not required_prefixes:
        return True
    for required in required_prefixes:
        for code in person_codes:
            if code.startswith(required):
                return True
    return False


def _age_at_year(person: PersonRecord, year: int) -> int:
    """Age on Jan 1 of ``year`` by DOB-year arithmetic."""
    if person.date_of_birth is None:
        return person.age
    return year - person.date_of_birth.year


def _attribute_in_scope(spec: AttributeSpec, person: PersonRecord, year: int) -> bool:
    """``clinical_scope`` evaluation. Both chronic-code prefix match
    and age-band containment must hold."""
    if not _chronic_codes_match(person.chronic_conditions, spec.clinical_scope.requires_chronic_codes):
        return False
    age = _age_at_year(person, year)
    lo, hi = spec.clinical_scope.requires_age_band
    return lo <= age <= hi


def _attribute_specificity(spec: AttributeSpec, person_codes: list[str]) -> int:
    """Longest matching required-prefix length for this person's chronic
    codes. Used to break ties when two Markov attributes target the same
    icd_base but have different ``requires_chronic_codes`` specificity
    (I69.3 sub-code vs I69 base-code fallback). An empty requirement
    list matches length 0 — intentionally lowest priority."""
    best = 0
    for required in spec.clinical_scope.requires_chronic_codes:
        for code in person_codes:
            if code.startswith(required):
                best = max(best, len(required))
    return best


def _select_markov_winners(
    specs: dict[str, AttributeSpec],
    in_scope: set[str],
    person: PersonRecord,
) -> set[str]:
    """Group in-scope Markov attributes by icd_base; return the single
    winning attribute_id per group under longest-prefix specificity
    (ties broken alphabetically on attribute_id for determinism).
    Non-Markov attributes always pass through — they live under their
    own latent_name / event namespace, not icd_base."""
    winners: set[str] = set()
    markov_by_icd: dict[str, list[str]] = {}
    for aid in in_scope:
        spec = specs[aid]
        if spec.pattern != "markov":
            winners.add(aid)
            continue
        markov_by_icd.setdefault(spec.body.icd_base, []).append(aid)
    for icd, candidates in markov_by_icd.items():
        if len(candidates) == 1:
            winners.add(candidates[0])
            continue
        candidates.sort(
            key=lambda aid: (
                -_attribute_specificity(specs[aid], person.chronic_conditions),
                aid,
            ),
        )
        winners.add(candidates[0])
    return winners


def _apply_pattern(
    spec: AttributeSpec,
    snapshot: YearSnapshot,
    rng: np.random.Generator,
    *,
    prev_snapshot: YearSnapshot | None,
    multiplier: float = 1.0,
) -> None:
    """Dispatch to the pattern's `initial` (prev is None) or `step`
    (prev provided). Mutates ``snapshot`` in place.

    ``multiplier`` is passed into the Markov step as a per-icd rate
    scalar (AR1 ignores it in Phase 2; could compose later as drift
    multiplier if ever needed). Default 1.0 preserves pre-Phase 2 behavior.
    """
    handler = PATTERN_REGISTRY[spec.pattern]
    if spec.pattern == "ar1":
        latent = spec.body.latent_name
        if prev_snapshot is None:
            value = handler["initial"](rng, spec.body)
        else:
            prev_value = prev_snapshot.continuous.get(latent)
            if prev_value is None:
                # mid-sim scope entry: fall through to initial draw
                value = handler["initial"](rng, spec.body)
            else:
                value = handler["step"](prev_value, rng, spec.body)
        snapshot.continuous[latent] = value
    elif spec.pattern == "markov":
        icd = spec.body.icd_base
        if prev_snapshot is None:
            value = handler["initial"](rng, spec.body)
        else:
            prev_value = prev_snapshot.chronic_stages.get(icd)
            if prev_value is None:
                # mid-sim scope entry: fall through to initial draw
                value = handler["initial"](rng, spec.body)
            else:
                value = handler["step"](prev_value, rng, spec.body, multiplier=multiplier)
        snapshot.chronic_stages[icd] = value
    else:
        # Phase 3 adds event → snapshot.new_complications etc.
        raise NotImplementedError(f"pattern {spec.pattern!r} not implemented in Phase 2")


def initial_snapshot(
    person: PersonRecord,
    year: int,
    init_rng: np.random.Generator,
) -> YearSnapshot:
    """Build the sim-start YearSnapshot for ``person`` at ``year``.

    Appends to ``person.longitudinal_history`` and returns the new snapshot.
    Raises ``ValueError`` when the person already has history for
    this year.
    """
    if person.longitudinal_history:
        raise ValueError(
            f"person {person.person_id!r} already has state_history "
            f"(last year={person.longitudinal_history[-1].year}); "
            f"use advance_one_year to extend."
        )
    snap = YearSnapshot(year=year)
    specs = load_attribute_specs()
    order = topological_order(specs)
    in_scope = {aid for aid in order if _attribute_in_scope(specs[aid], person, year)}
    winners = _select_markov_winners(specs, in_scope, person)
    for aid in order:
        if aid not in winners:
            continue
        _apply_pattern(specs[aid], snap, init_rng, prev_snapshot=None)
    person.longitudinal_history.append(snap)
    return snap


def advance_one_year(
    person: PersonRecord,
    year: int,
    year_rng: np.random.Generator,
    *,
    multiplier_fn: Callable[[PersonRecord, str, int], float] | None = None,
) -> YearSnapshot:
    """Advance ``person`` one year to ``year``.

    Appends a new YearSnapshot and returns it. Raises:
    - ``ValueError`` when ``state_history`` is empty (use ``initial_snapshot``).
    - ``ValueError`` on duplicate year (idempotency contract).
    - ``ValueError`` on backward year (monotonicity contract).

    ``multiplier_fn`` scales Markov transition probabilities per-icd
    per-year. Phase 2 wires ``aging._comorbidity_multiplier`` here so
    comorbidity-interaction rules in
    ``comorbidity_progression_multipliers.yaml`` compose with the Markov
    step. ``None`` → multiplier 1.0 (base rate).
    """
    if not person.longitudinal_history:
        raise ValueError(f"person {person.person_id!r} has empty state_history — call initial_snapshot first.")
    last_year = person.longitudinal_history[-1].year
    if year == last_year:
        raise ValueError(f"person {person.person_id!r} already advanced to year {year}")
    if year < last_year:
        raise ValueError(
            f"person {person.person_id!r} cannot advance backward: "
            f"last year {last_year}, requested {year} (prior to last)."
        )
    snap = YearSnapshot(year=year)
    prev = person.longitudinal_history[-1]
    specs = load_attribute_specs()
    order = topological_order(specs)
    in_scope = {aid for aid in order if _attribute_in_scope(specs[aid], person, year)}
    winners = _select_markov_winners(specs, in_scope, person)
    for aid in order:
        if aid not in winners:
            continue
        spec = specs[aid]
        if spec.pattern == "markov" and multiplier_fn is not None:
            mult = float(multiplier_fn(person, spec.body.icd_base, year))
        else:
            mult = 1.0
        _apply_pattern(spec, snap, year_rng, prev_snapshot=prev, multiplier=mult)
    person.longitudinal_history.append(snap)
    return snap


def state_at(
    person: PersonRecord,
    when: datetime | date | int,
) -> YearSnapshot:
    """Return the YearSnapshot matching ``when.year`` (or ``when`` if
    int). Pure lookup; no RNG. Raises ``IndexError`` on empty history
    or out-of-range year.

    Duck-typed on ``.longitudinal_history`` + ``.person_id`` /
    ``.patient_id`` so both PersonRecord (Layer-1) and PatientProfile
    (Layer-2, mirrored via activator) can be passed in."""
    # bool is a subclass of int in Python — reject explicitly so a
    # mistaken ``state_at(person, True)`` doesn't silently become
    # ``year=1``.
    if isinstance(when, bool):
        raise TypeError(f"state_at: unsupported when type {type(when).__name__}")
    _pid = getattr(person, "person_id", None) or getattr(person, "patient_id", "?")
    if not person.longitudinal_history:
        raise IndexError(f"person {_pid!r} has empty longitudinal_history")
    if isinstance(when, datetime):
        target_year = when.year
    elif isinstance(when, date):
        target_year = when.year
    elif isinstance(when, int):
        target_year = when
    else:
        raise TypeError(f"state_at: unsupported when type {type(when).__name__}")
    for snap in person.longitudinal_history:
        if snap.year == target_year:
            return snap
    raise IndexError(
        f"person {_pid!r} has no state for year {target_year} "
        f"(range: {person.longitudinal_history[0].year}..{person.longitudinal_history[-1].year})"
    )


__all__ = ["advance_one_year", "state_at", "initial_snapshot", "YearSnapshot"]
