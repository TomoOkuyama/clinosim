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

from collections.abc import Callable
from datetime import date, datetime
from typing import TYPE_CHECKING

import numpy as np

from clinosim.modules.longitudinal.loader import (
    AttributeSpec,
    load_attribute_specs,
    topological_order,
)
from clinosim.modules.longitudinal.patterns import PATTERN_REGISTRY
from clinosim.modules.longitudinal.patterns.ar1 import AR1Spec
from clinosim.modules.longitudinal.patterns.markov import MarkovSpec
from clinosim.modules.longitudinal.snapshot import YearSnapshot
from clinosim.seeding import longitudinal_event_seed

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
    """``clinical_scope`` evaluation. Sex-lock, chronic-code prefix
    match, and age-band containment must all hold."""
    if spec.clinical_scope.requires_sex and person.sex != spec.clinical_scope.requires_sex:
        return False
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
        assert isinstance(spec.body, MarkovSpec)
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


def _add_base_chronic_meds_for_new_icd(person: PersonRecord, new_icd: str) -> None:
    """Phase 4b.2.δ — invoke the chronic-medication activation sampler
    for a single newly-acquired ICD and merge any sampled drugs into
    ``person.current_medications``.

    Uses the per-patient ``chronic_medication_seed`` sub-RNG that the
    activator uses at base-year, so this call is RNG-shape neutral with
    respect to the engine's ``year_rng`` and cross-cohort byte-identical
    for patients who never acquire a new chronic mid-sim.
    """
    if not new_icd:
        return
    # Lazy imports: activator pulls in the full patient module graph; the
    # longitudinal engine is intentionally lean. Also breaks any import
    # cycle risk with population → longitudinal.
    from clinosim.locale.loader import load_chronic_medications
    from clinosim.modules.patient.activator import _derive_home_medications
    from clinosim.types.patient import ChronicCondition

    icd_base = new_icd.split(".")[0]
    yaml_data = load_chronic_medications()
    if new_icd not in yaml_data and icd_base not in yaml_data:
        return
    sampled = _derive_home_medications(
        [ChronicCondition(code=new_icd, system="icd-10-cm")],
        patient_id=person.person_id,
        country="US",
    )
    if not sampled:
        return
    existing_drug_names = {hm.drug_name for hm in person.current_medications if hm.drug_name}
    for hm in sampled:
        if hm.drug_name and hm.drug_name not in existing_drug_names:
            person.current_medications.append(hm)
            existing_drug_names.add(hm.drug_name)


def _apply_pattern(
    spec: AttributeSpec,
    snapshot: YearSnapshot,
    rng: np.random.Generator,
    *,
    prev_snapshot: YearSnapshot | None,
    multiplier: float = 1.0,
    person: PersonRecord | None = None,
) -> None:
    """Dispatch to the pattern's `initial` (prev is None) or `step`
    (prev provided). Mutates ``snapshot`` in place. Event-pattern
    attributes also mutate ``person.chronic_conditions`` on fire.

    ``multiplier`` is passed into the Markov step as a per-icd rate
    scalar (AR1 ignores it in Phase 2; could compose later as drift
    multiplier if ever needed). Default 1.0 preserves pre-Phase 2 behavior.
    """
    handler = PATTERN_REGISTRY[spec.pattern]
    if spec.pattern == "ar1":
        assert isinstance(spec.body, AR1Spec)
        latent = spec.body.latent_name
        ar1_value: float
        if prev_snapshot is None:
            ar1_value = handler["initial"](rng, spec.body)
        else:
            prev_cont = prev_snapshot.continuous.get(latent)
            if prev_cont is None:
                # mid-sim scope entry: fall through to initial draw
                ar1_value = handler["initial"](rng, spec.body)
            else:
                ar1_value = handler["step"](prev_cont, rng, spec.body)
        snapshot.continuous[latent] = ar1_value
    elif spec.pattern == "markov":
        assert isinstance(spec.body, MarkovSpec)
        icd = spec.body.icd_base
        stage_value: str
        age = _age_at_year(person, snapshot.year) if person is not None else None
        if prev_snapshot is None:
            stage_value = handler["initial"](rng, spec.body, age=age)
        else:
            prev_stage = prev_snapshot.chronic_stages.get(icd)
            if prev_stage is None:
                # mid-sim scope entry: fall through to initial draw
                stage_value = handler["initial"](rng, spec.body, age=age)
            else:
                stage_value = handler["step"](prev_stage, rng, spec.body, multiplier=multiplier)
        snapshot.chronic_stages[icd] = stage_value
    elif spec.pattern == "event":
        # Events read same-year AR1 latents via the just-filled
        # snapshot.continuous; the engine iterates attributes in topo
        # order, so hba1c executes before any event depending on it.
        if person is None:
            raise ValueError("event pattern dispatch requires person argument")
        prior = person.longitudinal_history or []
        # Phase 4b.2.α: context carries ``age`` (for age-band base rates)
        # and ``chronic_conditions`` (for has_chronic rate modifiers)
        # alongside the Phase 3 ``continuous`` latents. Keys unused by a
        # given yaml are inert; Phase 3/4a/4b.1 yamls stay byte-identical.
        _age = snapshot.year - person.date_of_birth.year if person.date_of_birth else 0
        context = {
            "continuous": dict(snapshot.continuous),
            "age": _age,
            "chronic_conditions": list(person.chronic_conditions),
        }
        event_rng = (
            np.random.default_rng(longitudinal_event_seed(person.person_id, snapshot.year, spec.body.event_name))
            if spec.body.rng_isolated
            else rng
        )
        result = handler["step"](
            person.chronic_conditions,
            prior,
            event_rng,
            spec.body,
            context=context,
        )
        if result.fired:
            if result.emits_icd:
                snapshot.new_complications.append(result.emits_icd)
                if result.emits_icd not in person.chronic_conditions:
                    person.chronic_conditions.append(result.emits_icd)
                # Clinical-coherence mutex: F33 (recurrent depressive
                # disorder) subsumes F32 (depressive episode, single)
                # per ICD-10-CM §F30-F39. When the F33 onset event
                # fires on a person already carrying F32 from the
                # initial-cohort sampler, drop F32 so the problem list
                # reflects the subsumption. The sampler applies the
                # same mutex at generation time; this call covers
                # mid-sim onset. RNG-shape neutral (no rng draw).
                # See ``clinosim/modules/population/condition_mutex.py``.
                from clinosim.modules.population.condition_mutex import (
                    apply_depression_mutex,
                )

                apply_depression_mutex(person.chronic_conditions)

                # Phase 4b.2.δ — activate base chronic medications for the
                # newly-acquired ICD. The Phase 4b.2.β onset events (e.g.
                # i10_onset, e11_9_onset, e03_onset) append the ICD to
                # ``person.chronic_conditions`` mid-sim but nothing invoked
                # the chronic-medication activation sampler for that single
                # new code, so the base home regimen (Amlodipine for I10,
                # Metformin for E11.9, Levothyroxine for E03, …) never
                # populated. Then Phase 4a / 4b.1 escalation events — which
                # gate on vitals/labs, not drug prerequisites — fired on top
                # of nothing, producing implausible histories like HCTZ-only
                # monotherapy for new-onset HTN (cycle-2 audit finding
                # #1737, observed on POP-001334 in US seed=42 p=2000 5y).
                #
                # Mirror of the Phase 4b.2.γ scope re-evaluation pattern:
                # the activation call uses a patient-id-seeded sub-RNG
                # (``chronic_medication_seed``), so it is RNG-shape neutral
                # with respect to ``year_rng`` — unrelated patients /
                # unrelated code paths see no cursor shift. Dedup on
                # ``drug_name`` prevents a duplicate when a patient already
                # carries one of the base-regimen drugs from elsewhere.
                _add_base_chronic_meds_for_new_icd(person, result.emits_icd)
            # snapshot.med_additions carries the fire_marker when set (dedup
            # token for Task 2's prior-year scan + CIF emit resolves back
            # via fire_marker → spec lookup). When no fire_marker is set,
            # fall back to drug names so a yaml-authoring omission still
            # produces visible provenance.
            fire_marker = getattr(spec.body, "fire_marker", "") or ""
            if fire_marker:
                snapshot.med_additions.append(fire_marker)
            elif result.med_additions:
                snapshot.med_additions.extend(result.med_additions)
            snapshot.med_removals.extend(result.med_removals)
            # #1754: retract baseline agents replaced by this event (e.g.
            # Atorvastatin removed when Rosuvastatin fires in the
            # high-intensity statin switch). Removals happen BEFORE
            # additions so a substitution where the add is the same as
            # the removal is a no-op rather than a double-remove.
            if result.med_removals:
                _retract = {str(name) for name in result.med_removals}
                person.current_medications = [
                    hm for hm in person.current_medications if (hm.drug_name or "") not in _retract
                ]
            if result.med_additions:
                from clinosim.modules.longitudinal.med_lookup import resolve_med_name

                existing_drug_names = {hm.drug_name for hm in person.current_medications}
                for drug_name in result.med_additions:
                    if drug_name in existing_drug_names:
                        continue
                    person.current_medications.append(resolve_med_name(drug_name))
                    existing_drug_names.add(drug_name)
    else:  # pragma: no cover — guarded by _IMPLEMENTED_PATTERNS
        raise NotImplementedError(f"pattern {spec.pattern!r} not implemented")


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
        _apply_pattern(specs[aid], snap, init_rng, prev_snapshot=None, person=person)
    # Phase 4b.2.γ: see `advance_one_year` — an event may have added a
    # chronic code mid-pass; dispatch any newly-in-scope Markov on the
    # same snapshot via its initial draw.
    post_scope = {aid for aid in order if _attribute_in_scope(specs[aid], person, year)}
    newly_in_scope = post_scope - in_scope
    if newly_in_scope:
        post_winners = _select_markov_winners(specs, post_scope, person)
        for aid in order:
            if aid not in newly_in_scope or aid not in post_winners:
                continue
            spec = specs[aid]
            if spec.pattern != "markov":
                continue
            assert isinstance(spec.body, MarkovSpec)
            if spec.body.icd_base in snap.chronic_stages:
                continue
            _apply_pattern(spec, snap, init_rng, prev_snapshot=None, person=person)
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

    Year gaps (``year > last+1``) are PERMITTED: the production
    ``advance_population`` pipeline legitimately jumps from
    ``initial_snapshot(base_year)`` to the sim window's start year,
    which may be several years later. A per-call gap guard would
    break that flow. ``state_at`` only resolves years that have been
    advanced through, so an unvisited year raises ``IndexError`` on
    lookup rather than silently returning stale state.

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
            assert isinstance(spec.body, MarkovSpec)
            mult = float(multiplier_fn(person, spec.body.icd_base, year))
        else:
            mult = 1.0
        _apply_pattern(spec, snap, year_rng, prev_snapshot=prev, multiplier=mult, person=person)
    # Phase 4b.2.γ: an event dispatched above may have appended a new
    # chronic code to `person.chronic_conditions`; re-evaluate scope so a
    # Markov attribute newly gated-in by that code dispatches its initial
    # stage draw on this same year's snapshot, not next year's. RNG draws
    # are strictly additive — attributes already dispatched above don't
    # re-draw. Cohorts without a mid-sim event→Markov acquisition stay
    # byte-identical.
    post_scope = {aid for aid in order if _attribute_in_scope(specs[aid], person, year)}
    newly_in_scope = post_scope - in_scope
    if newly_in_scope:
        post_winners = _select_markov_winners(specs, post_scope, person)
        for aid in order:
            if aid not in newly_in_scope or aid not in post_winners:
                continue
            spec = specs[aid]
            if spec.pattern != "markov":
                continue
            assert isinstance(spec.body, MarkovSpec)
            if spec.body.icd_base in snap.chronic_stages:
                continue
            _apply_pattern(spec, snap, year_rng, prev_snapshot=prev, multiplier=1.0, person=person)
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
