"""Per-person biology initialisation (Issue #1581 Phase A).

A newborn registered mid-simulation via
:func:`clinosim.modules.population.newborn.register_newborn` must end
up with the same per-person state an age-0 citizen of the initial
cohort would have — otherwise downstream aging passes (allergy drift,
reactive mortality) short-circuit and the "post-discharge newborn ≈
regular citizen" invariant breaks.

This module hosts the shared per-person entry points so the initial-
cohort POST_POPULATION enrichers and the mid-sim newborn registration
converge on identical semantics.

Phase A current scope (this PR):

* :func:`initialize_newborn_biology` — assigns a NKA allergy baseline
  and pre-samples a natural-death date for a freshly-registered
  newborn.

Phase A follow-up (not yet in this PR):

* identity + insurance enrolment per-person entry (household-level
  shared-RNG draw makes extraction less trivial — handled separately).

Phase B (separate PR):

* ``advance_population`` secondary pass covering newborns in years
  after their birth so chronic onset / stage progression / allergy
  drift / reactive mortality catch up.

Phase C (separate PR):

* ABO + Rh parent-to-child inheritance; atopic predisposition from
  parent atopic status.
"""

from __future__ import annotations

from typing import Any

from clinosim.modules.allergy.engine import _make_nka, load_allergen_config
from clinosim.modules.natural_death.enricher import (
    sample_person_death_date,
    sim_window,
)


def initialize_newborn_biology(person: Any, config: Any) -> None:
    """Attach the per-person state a newborn needs to be indistinguishable
    from an initial-cohort citizen at age 0.

    Currently populates two fields that the Phase 1 ``register_newborn``
    left at their dataclass defaults:

    * ``person.allergies`` — set to a single NKA (no known allergies)
      positive-assertion record, matching the invariant the
      POST_POPULATION ``allergy_enricher`` enforces for every initial-
      cohort person. Real food / drug allergies for the newborn still
      emerge over time through ``aging._allergy_drift`` as the child
      ages (late-onset drug sensitivity for adults) and through a
      future childhood-onset pass; starting at NKA is the clinically
      correct baseline (true delivery-day allergies are rare).

    * ``person.date_of_death`` — pre-sampled over the sim window using
      the same per-year qx Bernoulli as the initial-cohort
      ``sample_natural_deaths`` enricher. A newborn that would die of
      natural causes within the sim window now gets a concrete death
      date, which the ``is_alive_at`` filter uses to stop event
      emission from that date forward (symmetric with existing
      citizens).

    No-op branches (chosen so test fixtures that build a
    ``PatientProfile`` without a full config keep working):

    * ``config is None`` → return without any writes.
    * ``allergen_config`` yaml missing / empty → skip the allergy write.
    * ``sim_window`` unresolvable or life-table missing → skip the
      death-date write.

    The function mutates ``person`` in place and returns None.
    """
    if config is None:
        return

    try:
        allergen_cfg = load_allergen_config()
    except Exception:
        allergen_cfg = {}
    nka_cfg = (allergen_cfg or {}).get("nka") or {}
    if nka_cfg and person.allergies is None:
        person.allergies = [_make_nka(nka_cfg)]

    master_seed = int(getattr(config, "random_seed", 0) or 0)
    country = getattr(config, "country", "US") or "US"
    window = sim_window(config)
    if window is None:
        return
    sample_person_death_date(person, country, master_seed, window)
