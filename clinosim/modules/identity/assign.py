"""Population-facing numbering pass (AD-54).

Runs AFTER population generation as a separate pass with a dedicated sub-seed
Generator, so the main simulation random stream (and golden files) is untouched
(AD-16). Attaches an `IdentityTimeline` to each `PersonRecord` in place.
"""

from __future__ import annotations

import hashlib
from typing import Any

import numpy as np

from clinosim.locale.loader import load_identity_config
from clinosim.modules.identity.registry import get_provider
from clinosim.seeding import ENRICHER_SEED_OFFSETS
from clinosim.types import IdentityTimeline


def assign_identities(registry: Any, country: str, master_seed: int) -> None:
    """Assign insurance enrollment + national identity to every resident.

    No-op for countries without an `identity.yaml` (e.g. US in Phase 1), which keep
    their existing insurance handling.

    Issue #1581 — the per-household latent is now also PERSISTED on
    ``Household.identity_latent`` so a per-person entry (used when a
    newborn joins the household mid-sim) can re-use the same latent
    and preserve the intra-household card-holding correlation this
    batch pass establishes.
    """
    config = load_identity_config(country)
    if not config:
        return

    provider = get_provider(country)
    rng = np.random.default_rng(master_seed + ENRICHER_SEED_OFFSETS["identity"])

    for household in registry.households:
        members = household.members
        if not members:
            continue
        enrollments = provider.assign_household(members, rng, config)
        household_latent = float(rng.standard_normal())  # shared draw → intra-household corr.
        household.identity_latent = household_latent
        for m in members:
            identity = provider.assign_personal(m, household_latent, rng, config)
            enrollment = enrollments.get(m.person_id)
            m.identity = IdentityTimeline(
                national=identity,
                enrollments=[enrollment] if enrollment is not None else [],
            )


def assign_identity_for_person(
    registry: Any,
    person: Any,
    country: str,
    master_seed: int,
) -> None:
    """Attach an ``IdentityTimeline`` to a single person after the
    batch :func:`assign_identities` has already run on the registry.

    Used by :func:`clinosim.modules.population.newborn.register_newborn`
    to give mid-sim-added citizens the same per-person identity + insurance
    that initial-cohort citizens get, so the newborn is behaviourally
    indistinguishable from an age-0 initial-cohort person on
    ``PersonRecord.identity`` (closing the Issue #1581 identity gap).

    No-op for countries without an ``identity.yaml`` (e.g. US) and
    for persons whose household is not resolvable from ``registry.
    households``. The per-person sub-RNG is derived from
    ``master_seed + ENRICHER_SEED_OFFSETS["identity"] + sha(person_id)``
    so this call does not consume from the shared enricher stream the
    batch pass used — stream byte-identity for the initial cohort is
    preserved.

    The ``household_latent`` persisted by the batch pass on
    ``Household.identity_latent`` is reused when present so the
    newborn's card-holding sample stays correlated with the household's
    other members (same intra-household correlation the batch pass
    established). Falls back to 0.0 (no correlation) for test fixtures
    that bypass the batch pass.
    """
    config = load_identity_config(country)
    if not config:
        return
    provider = get_provider(country)

    household_id = getattr(person, "household_id", None)
    household = None
    if household_id is not None:
        household = next(
            (h for h in registry.households if h.household_id == household_id),
            None,
        )
    household_latent = float(getattr(household, "identity_latent", None) or 0.0)

    pid = getattr(person, "person_id", "")
    salt = hashlib.sha256(f"{master_seed}|identity_person|{pid}|v1".encode()).digest()
    sub_seed = int.from_bytes(salt[:4], "big") + master_seed + ENRICHER_SEED_OFFSETS["identity"]
    rng = np.random.default_rng(sub_seed)

    enrollments = provider.assign_household([person], rng, config)
    identity = provider.assign_personal(person, household_latent, rng, config)
    enrollment = enrollments.get(person.person_id)
    person.identity = IdentityTimeline(
        national=identity,
        enrollments=[enrollment] if enrollment is not None else [],
    )
