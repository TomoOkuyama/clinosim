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


__all__ = ["register_newborn"]


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
    from POST_POPULATION enrichers (NKA allergy baseline + pre-sampled
    natural death date). Callers that pre-date the Phase A hook (test
    fixtures that build a ``PatientProfile`` directly without a config)
    may pass ``config=None`` to skip the biology init and preserve the
    original Phase 1 behaviour.
    """
    # Idempotent re-registration.
    existing = registry.persons.get(newborn.patient_id)
    if existing is not None:
        return existing

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
        is_alive=True,
    )

    registry.persons[newborn.patient_id] = record

    # Attach to the mother's household (same household_id as the mother).
    for household in registry.households:
        if household.household_id == mother.household_id:
            if record not in household.members:
                household.members.append(record)
            break

    # Phase A biology init — matches the per-person state an initial-
    # cohort citizen at age 0 would have (NKA allergy baseline, pre-
    # sampled natural-death date). ``initialize_newborn_biology`` is a
    # no-op when ``config`` is None (test fixtures without a full sim
    # config), preserving the original Phase 1 behaviour for those
    # callers.
    initialize_newborn_biology(record, config)

    return record
