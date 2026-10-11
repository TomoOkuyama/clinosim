"""Annual population-aging hook (Issue #1564 Phase 2 scaffold).

Called by the engine at the top of each simulated year. Walks every
alive person in the registry and lets per-person "aging passes" update
their state before the year's events are generated:

* :func:`_annual_chronic_onset` — age × sex × SDOH incidence of newly
  acquired chronic conditions (e.g. a 60-year-old without diabetes at
  year 0 can develop it at year 3). Marginal-preserving at cohort scope:
  sim-end prevalence must still match the hospital-cohort target.
* :func:`_disease_progression` — stage advancement (CKD G1→G5,
  COPD GOLD I→IV, diabetes compensated→decompensated).
* :func:`_allergy_drift` — childhood food-allergy resolution and
  late-onset drug-sensitivity emergence.
* :func:`_condition_reactive_mortality` — replace ``natural_death``'s
  single pre-sampled date with a lazy per-year Bernoulli that factors
  the person's current condition load.

Scope of this PR (scaffold only):

* Public :func:`advance_population` entry point, wired into the engine's
  year loop so later PRs can attach behaviour without touching the
  engine again.
* Four pass stubs, each a no-op that documents its intended contract.
* No behavioural change — byte-identity preserved for every existing
  cohort. Determinism gate stays green.
* Follow-up PRs within Phase 2 fill in the pass bodies one at a time.

Determinism contract:

* Each pass receives a per-(person, year, pass_name) sub-RNG derived
  deterministically from ``(person_id, year, pass_name)`` — no shared
  stream between passes or between persons. This isolates each pass's
  draws so adding behaviour in Phase 2 does not cascade into unrelated
  cohort output.
"""

from __future__ import annotations

import hashlib

import numpy as np

from clinosim.types.population import PersonRecord

__all__ = [
    "advance_population",
    "aging_sub_seed",
]


_AGING_SEED_SALT = "clinosim:aging:v1"


def aging_sub_seed(person_id: str, year: int, pass_name: str) -> int:
    """Deterministic 32-bit sub-seed for one person × year × aging pass.

    Derived from ``(person_id, year, pass_name)`` so every pass gets an
    isolated stream — a change inside ``_disease_progression`` cannot
    shift ``_annual_chronic_onset`` draws for the same person, and a
    change for one person cannot shift anyone else's streams.
    """
    key = f"{_AGING_SEED_SALT}|{person_id}|{year}|{pass_name}"
    return int(hashlib.sha256(key.encode()).hexdigest(), 16) % (2**32)


def _annual_chronic_onset(person: PersonRecord, year: int, prng: np.random.Generator) -> None:
    """Per-person annual chronic-condition onset (Phase 2 stub).

    Future contract (not yet implemented): draw against age × sex ×
    SDOH-adjusted annual incidence tables from
    ``clinosim/locale/*/chronic_annual_incidence.yaml`` and append
    newly acquired ICD codes to ``person.chronic_conditions`` with
    ``onset_date = date(year, mid, 15)``. Marginal-preserving: initial
    sampling leaves ``future incidence budget`` headroom so sim-end
    prevalence matches the hospital-cohort target. No-op in the
    scaffold PR; later PRs within Phase 2 attach behaviour.
    """


def _disease_progression(person: PersonRecord, year: int, prng: np.random.Generator) -> None:
    """Per-person annual disease-stage advancement (Phase 2 stub).

    Future contract: use existing physiology state where it exists;
    otherwise YAML-driven annual transition matrices to advance
    CKD stage, COPD GOLD stage, diabetes compensation, dementia
    progression. No-op in the scaffold PR.
    """


def _allergy_drift(person: PersonRecord, year: int, prng: np.random.Generator) -> None:
    """Per-person annual allergy drift (Phase 2 stub).

    Future contract: childhood food-allergy resolution rates by age,
    late-onset drug-sensitivity emergence after exposure. Mutates
    ``person.allergies`` in place. No-op in the scaffold PR.
    """


def _condition_reactive_mortality(person: PersonRecord, year: int, prng: np.random.Generator) -> None:
    """Per-person annual condition-reactive mortality draw (Phase 2 stub).

    Future contract: replace the ``natural_death`` enricher's single
    pre-sampled ``date_of_death`` with a lazy per-year Bernoulli that
    factors the person's current condition load. Keeps actuarial ``qx``
    as the baseline multiplier. No-op in the scaffold PR.
    """


def advance_population(
    registry: object,
    year: int,
) -> None:
    """Advance the population by one simulated year (Phase 2 scaffold).

    Called by the engine at the top of each year's iteration, before
    that year's monthly events are generated. Walks every alive person
    and runs the four aging passes with per-(person, year, pass) sub-
    RNGs so each pass stays stream-isolated and byte-identical across
    runs with the same global seed.

    ``registry`` is typed as ``object`` to avoid a cyclic import with
    ``clinosim.modules.population.engine``; the runtime guard narrows
    it. The scaffold invocation is a no-op (all four passes return
    without touching state), so initial-cohort output is byte-identical
    to pre-change master. Later PRs within Phase 2 attach behaviour to
    the pass stubs.
    """
    from clinosim.modules.population.engine import PopulationRegistry

    assert isinstance(registry, PopulationRegistry), "advance_population: registry must be a PopulationRegistry"

    for person in registry.persons.values():
        if not person.is_alive:
            continue
        for pass_fn in (
            _annual_chronic_onset,
            _disease_progression,
            _allergy_drift,
            _condition_reactive_mortality,
        ):
            pass_rng = np.random.default_rng(aging_sub_seed(person.person_id, year, pass_fn.__name__))
            pass_fn(person, year, pass_rng)
