"""Newborn → PersonRecord registration (Issue #1564 Phase 1 scaffold).

Perinatal (``clinosim.simulator.perinatal``) emits a
``PatientProfile`` for every liveborn baby at the delivery encounter.
Before this module existed those babies were never promoted to a
long-lived :class:`PersonRecord` in the
:class:`clinosim.modules.population.engine.PopulationRegistry`, so they
disappeared from subsequent year iterations: no pediatric well-child
visits, no immunizations, no life events after discharge.

``register_newborn`` closes the gap by minting a ``PersonRecord`` from a
freshly-built newborn ``PatientProfile`` and inserting it into both the
registry's ``persons`` dict and the mother's ``Household.members`` list.
Downstream iteration over ``registry.persons.values()`` picks the
newborn up on the next loop automatically.

Scope of this PR (Issue #1564 Phase 1 — scaffold only):

* Mint and register the ``PersonRecord``.
* Idempotent: re-registration with the same newborn id is a no-op.
* The registered newborn is tagged outside
  ``registry.initial_person_ids``, so callers can keep iterating the
  initial cohort under its original RNG spawn shape without a byte-diff
  cascade.

Explicitly NOT in this PR (follow-up within Phase 1):

* Actually generating pediatric calendar / immunization events for the
  registered newborn. The event-generation path in
  ``clinosim.simulator.engine`` iterates the registry *before* the
  delivery dispatcher runs, so no newborn pediatric events fire yet
  even after this scaffold lands. A follow-up PR adds a secondary
  pass that re-runs ``generate_monthly_events`` for newborns over the
  years after birth.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from clinosim.modules.population.person_init import initialize_newborn_biology
from clinosim.types.population import PersonRecord

if TYPE_CHECKING:
    from clinosim.modules.population.engine import PopulationRegistry
    from clinosim.types.patient import PatientProfile


__all__ = ["register_newborn", "find_household_father"]


# Atopic-march inheritance ORs for child allergy risk, per Bousquet et
# al 2008 (Allergy 63:5) and Hong et al 2012 (Pediatr Allergy Immunol
# 23:234). Single-parent OR ≈ 2 (one atopic parent), two-parent OR
# ≈ 3.5 (both atopic). We cap at the single-parent value when only
# the mother is observed in the household.
_ATOPIC_INHERITANCE_MULTIPLIER_ONE_PARENT = 2.0
_ATOPIC_INHERITANCE_MULTIPLIER_TWO_PARENTS = 3.5


def find_household_father(mother: PersonRecord, registry: PopulationRegistry) -> PersonRecord | None:
    """Heuristic household-father lookup for Phase C.2 inheritance paths.

    Returns the registered male adult (age ≥ 18) in the mother's
    household who is closest in age to the mother, or ``None`` when
    no such person exists. The ``Household`` dataclass does not carry
    an explicit relationship field (father / husband / partner), so
    this heuristic is a best-effort proxy and is intentionally
    conservative — same-sex partnerships and single-mother households
    simply get ``None`` here, falling through to the mother-only
    inheritance path used in Phase C.1.

    The heuristic is monotone in household membership, so adding a
    newborn (who is age 0, not an adult) does not change the father
    identification for later siblings.
    """
    if getattr(mother, "sex", "") != "F":
        return None
    household = next((h for h in registry.households if h.household_id == mother.household_id), None)
    if household is None:
        return None
    candidates = [
        m
        for m in household.members
        if m.person_id != mother.person_id and getattr(m, "age", 0) >= 18 and getattr(m, "sex", "") == "M"
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda m: abs(getattr(m, "age", 0) - getattr(mother, "age", 0)))


def _is_atopic(person: PersonRecord | None) -> bool:
    """Return True iff the person carries any real active allergy
    (non-NKA, non-resolved) on their ``allergies`` list."""
    if person is None:
        return False
    allergies = getattr(person, "allergies", None) or []
    for a in allergies:
        if getattr(a, "is_nka", False):
            continue
        if getattr(a, "clinical_status", "") == "resolved":
            continue
        return True
    return False


def _atopic_predisposition_from_parents(
    mother: PersonRecord,
    father: PersonRecord | None,
) -> float:
    """Return the atopic-predisposition multiplier for a newborn given
    both parents. 1.0 when neither is atopic (clinically neutral), 2.0
    when only one is atopic (single-parent OR), 3.5 when both are
    atopic (two-parent OR). ``father=None`` collapses to the Phase C.1
    behaviour (mother-only).
    """
    atopic_parents = int(_is_atopic(mother)) + int(_is_atopic(father))
    if atopic_parents >= 2:
        return _ATOPIC_INHERITANCE_MULTIPLIER_TWO_PARENTS
    if atopic_parents == 1:
        return _ATOPIC_INHERITANCE_MULTIPLIER_ONE_PARENT
    return 1.0


def register_newborn(
    registry: PopulationRegistry,
    mother: PersonRecord,
    newborn: PatientProfile,
    config: Any = None,
) -> PersonRecord:
    """Promote ``newborn`` (a freshly-built delivery-side
    ``PatientProfile``) to a ``PersonRecord`` and insert into
    ``registry``.

    Idempotent — if ``newborn.patient_id`` is already a key in
    ``registry.persons``, the existing record is returned unchanged
    (useful when the delivery dispatcher is retried for a given event).

    The returned ``PersonRecord`` is NOT added to
    ``registry.initial_person_ids`` on purpose: callers can keep
    iterating the initial cohort under its original RNG spawn shape and
    treat newborns as a separate stream.

    The mother's household is updated in-place: the newborn joins
    ``Household.members`` (so household-scoped queries see the baby).
    If the mother's household is not resolvable from
    ``registry.households``, only ``registry.persons`` is updated — the
    sim still works but household membership is incomplete for that
    newborn.

    When ``config`` is provided (Issue #1581 Phase A), the registered
    newborn also goes through
    :func:`~clinosim.modules.population.person_init.initialize_newborn_biology`,
    which attaches the per-person state an initial-cohort citizen gets
    from POST_POPULATION enrichers (NKA allergy baseline, birth-year
    community-death draw). Callers that pre-date the Phase A hook (test
    fixtures that build a ``PatientProfile`` directly without a config)
    may pass ``config=None`` to skip the biology init and preserve the
    original Phase 1 behaviour.
    """
    # Idempotent re-registration.
    existing = registry.persons.get(newborn.patient_id)
    if existing is not None:
        return existing

    # Issue #1581 Phase C.2 extension — look up the household father
    # (heuristic: opposite-sex adult in the same household closest in
    # age to the mother). ``None`` collapses the parent-aware
    # inheritance paths to the single-parent / population-fallback
    # behaviour from Phase C.1.
    father = find_household_father(mother, registry)

    # If the father is identified AND a config was supplied, re-derive
    # ABO + Rh using both parents' phenotypes so the newborn
    # PatientProfile and the long-lived PersonRecord match a
    # biologically-correct two-parent cross. The perinatal builder
    # only has the mother available at construction time and samples
    # with the locale allele frequency as the father-side fallback;
    # we overwrite in place so the downstream FHIR Patient resource
    # (built from this PatientProfile) carries the two-parent result.
    # Deterministic SHA-based inheritance remains byte-identical for
    # the same (mother, father, newborn_id, country) tuple.
    if father is not None and config is not None:
        from clinosim.modules.population.inheritance import (
            derive_newborn_blood_type as _derive_abo_two_parent,
        )
        from clinosim.modules.population.inheritance import (
            derive_newborn_rh_factor as _derive_rh_two_parent,
        )

        country = getattr(config, "country", "US") or "US"
        newborn.blood_type = _derive_abo_two_parent(
            newborn.patient_id,
            getattr(mother, "blood_type", "A") or "A",
            country=country,
            father_blood_type=getattr(father, "blood_type", "A") or "A",
        )
        newborn.rh_factor = _derive_rh_two_parent(
            newborn.patient_id,
            getattr(mother, "rh_factor", "+") or "+",
            country=country,
            father_rh_factor=getattr(father, "rh_factor", "+") or "+",
        )

    # `PatientProfile.date_of_birth` is `date | None`; `PersonRecord`
    # requires `date`. Perinatal always stamps a real delivery date
    # when it builds the newborn profile, but guard the type contract
    # explicitly so a malformed caller fails loudly here rather than
    # silently inserting a bad record.
    if newborn.date_of_birth is None:
        raise ValueError(
            f"register_newborn: newborn {newborn.patient_id!r} has no "
            f"date_of_birth; perinatal must stamp the delivery date before "
            f"registration",
        )

    name = newborn.name
    address = newborn.address
    contact = newborn.contact

    record = PersonRecord(
        person_id=newborn.patient_id,
        household_id=newborn.household_id,
        age=0,
        sex=newborn.sex,
        date_of_birth=newborn.date_of_birth,
        family_name=name.family_name if name is not None else "",
        given_name=name.given_name if name is not None else "",
        # Issue #1581 Phase C.1 — phonetic (JP 戸籍 kana reading of the
        # surname) is inherited from the mother's PatientProfile via
        # `_build_newborn_patient`. This writethrough carries that
        # phonetic to the long-lived PersonRecord so later encounters
        # of the same child re-use the family phonetic reading.
        phonetic=name.phonetic if name is not None else None,
        # Issue #1581 Phase C.1 — ABO and Rh factor arrive from
        # `_build_newborn_patient` where they were sampled via
        # `inheritance.derive_newborn_blood_type` / `derive_newborn_rh_factor`
        # (mother phenotype × locale allele frequency). The `else "A"` /
        # `else "+"` fallbacks remain for test fixtures that bypass the
        # perinatal builder and construct a PatientProfile with the
        # dataclass defaults, which clinosim treated as blank sentinels
        # before this PR.
        blood_type=newborn.blood_type if newborn.blood_type else "A",
        rh_factor=newborn.rh_factor if newborn.rh_factor else "+",
        postal_code=address.postal_code,
        state=address.state,
        city=address.city,
        address_line=address.line1,
        phone_home=contact.phone_home,
        phone_mobile="",  # newborns do not have a mobile line
        # Perinatal conditions sampled in `simulator/perinatal.py`
        # (`_sample_newborn_conditions`) land on `newborn.chronic_conditions`
        # as `ChronicCondition` objects; mirror their ICD codes here so
        # the population-side view matches the FHIR-side view.
        chronic_conditions=[c.code for c in newborn.chronic_conditions if c.code],
        occupation=newborn.occupation or "infant",
        bmi=float(newborn.bmi) if newborn.bmi else 12.8,
        smoking_status="never",
        alcohol_use="none",
        # Issue #1581 Phase C.2 — atopic-march inheritance multiplier.
        # When the mother carries any real (non-NKA, non-resolved)
        # allergy, raise the newborn's per-year emergence rate for new
        # allergies in `aging._allergy_drift` by `_ATOPIC_INHERITANCE_
        # MULTIPLIER` (2.0, single-atopic-parent OR per Bousquet 2008
        # Allergy and Hong 2012 Pediatr Allergy Immunol). Mothers with
        # only a NKA record (allergen_code 716186003 or `is_nka=True`)
        # or whose only allergy is resolved (childhood food allergy
        # outgrown) are treated as non-atopic. Default (1.0) is the
        # initial-cohort generator's value — RNG-neutral for existing
        # citizens.
        atopic_predisposition=_atopic_predisposition_from_parents(mother, father),
        # Issue #1581 — race / ethnicity inherited from the mother's
        # PersonRecord. These are family-level attributes (OMB race
        # category + hispanic / not_hispanic ethnicity); a newborn
        # takes the mother's values. Empty mother values (JP cohort
        # with no race_distribution, or test fixtures) fall through
        # to the newborn's own empty defaults, matching how the
        # activator falls back to in-call sampling in that case.
        race=getattr(mother, "race", "") or "",
        ethnicity=getattr(mother, "ethnicity", "") or "",
    )

    # Issue #1581 Phase C.3 — Mendelian inheritance for single-gene
    # diseases (CF / SCD autosomal recessive in this slice; X-linked
    # follow-up). Walk the catalog and compute each disease's child
    # phenotype from (mother, father) phenotypes via SHA-seeded Punnett.
    # Affected newborns get the ICD code appended to chronic_conditions.
    from clinosim.locale.loader import load_single_gene_diseases
    from clinosim.modules.population.single_gene_inheritance import apply_newborn_inheritance

    _sgd_catalog = (load_single_gene_diseases() or {}).get("single_gene_diseases") or {}
    if _sgd_catalog:
        _sgd_affected = apply_newborn_inheritance(record, mother, father, _sgd_catalog)
        for _affected_code in _sgd_affected:
            if _affected_code not in record.chronic_conditions:
                record.chronic_conditions.append(_affected_code)

    registry.persons[newborn.patient_id] = record

    # Attach to the mother's household (same household_id as the mother).
    for household in registry.households:
        if household.household_id == mother.household_id:
            if record not in household.members:
                household.members.append(record)
            break

    # Phase A biology init — matches the per-person state an initial-
    # cohort citizen at age 0 would have (NKA allergy baseline, birth-
    # year community-death draw, pediatric care-seeking threshold,
    # Issue #1581 identity-timeline when the locale has a yaml). The
    # ``registry`` is passed through so the identity init can resolve
    # the mother's household and reuse the persisted intra-household
    # latent. ``initialize_newborn_biology`` is a no-op when ``config``
    # is None (test fixtures), preserving the original Phase 1 behaviour.
    initialize_newborn_biology(record, config, registry)

    return record
