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

Phase A current scope:

* :func:`initialize_newborn_biology` — assigns a NKA allergy baseline,
  pre-samples a natural-death date, and samples a care-seeking
  threshold from the locale's pediatric band for a freshly-registered
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

import hashlib
from typing import Any

import numpy as np

from clinosim.modules.allergy.engine import _make_nka, load_allergen_config
from clinosim.modules.natural_death.enricher import (
    sample_person_death_date,
    sim_window,
)


def _init_newborn_care_seeking_threshold(person: Any, config: Any) -> None:
    """Sample a care-seeking severity threshold for the newborn from the
    locale's pediatric age-conditional band (same age-0 lookup the
    initial cohort generator in ``clinosim.modules.population.engine``
    performs for pediatric citizens). Matches the ``care_seeking``
    config layout: ``age_conditional["0-14"]`` or
    ``threshold_mean`` fallback, with ``threshold_sd`` from the same
    block or the module-level default. Clamped to the locale's
    operational band ``[CARE_SEEKING_CLAMP_MIN, CARE_SEEKING_CLAMP_MAX]``.

    Deterministic: the per-newborn RNG is seeded off a stable hash of
    the newborn's person_id, so the sample is reproducible and does
    not consume the master simulation stream (byte-identity for the
    initial cohort stream is preserved).
    """
    from clinosim.locale.loader import load_demographics
    from clinosim.modules.population.engine import (
        CARE_SEEKING_CLAMP_MAX,
        CARE_SEEKING_CLAMP_MIN,
        CARE_SEEKING_THRESHOLD_SD_DEFAULT,
        _care_seeking_threshold_mean,
    )

    country = getattr(config, "country", "US") or "US"
    try:
        demo = load_demographics(country)
    except Exception:
        return
    cs = (demo or {}).get("care_seeking") or {}
    mean = _care_seeking_threshold_mean(demo or {}, 0)
    sd = float(cs.get("threshold_sd", CARE_SEEKING_THRESHOLD_SD_DEFAULT))

    pid = getattr(person, "person_id", "")
    seed = int(hashlib.sha256(f"{pid}|care_seeking_threshold|v1".encode()).hexdigest(), 16) % (2**32)
    rng = np.random.default_rng(seed)
    threshold = float(rng.normal(mean, sd))
    threshold = max(CARE_SEEKING_CLAMP_MIN, min(CARE_SEEKING_CLAMP_MAX, threshold))
    person.care_seeking_threshold = threshold


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

    * ``person.care_seeking_threshold`` — sampled from the locale's
      ``care_seeking.age_conditional["0-14"]`` pediatric band (same
      lookup the initial cohort generator uses for pediatric
      citizens), rather than falling through to the ``PersonRecord``
      dataclass default of 0.3 which was the adult-generator mean.
      Deterministic SHA-seeded per-person RNG so the sample is
      reproducible and does not consume the master stream.

    No-op branches (chosen so test fixtures that build a
    ``PatientProfile`` without a full config keep working):

    * ``config is None`` → return without any writes.
    * ``allergen_config`` yaml missing / empty → skip the allergy write.
    * ``sim_window`` unresolvable or life-table missing → skip the
      death-date write.
    * ``demographics.yaml`` yaml missing → skip the care-seeking
      sample (``PersonRecord`` dataclass default retained).

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
    if window is not None:
        sample_person_death_date(person, country, master_seed, window)

    _init_newborn_care_seeking_threshold(person, config)
