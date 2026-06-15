"""Population-facing numbering pass (AD-54).

Runs AFTER population generation as a separate pass with a dedicated sub-seed
Generator, so the main simulation random stream (and golden files) is untouched
(AD-16). Attaches an `IdentityTimeline` to each `PersonRecord` in place.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from clinosim.locale.loader import load_identity_config
from clinosim.modules.identity.registry import get_provider
from clinosim.types import IdentityTimeline

# Dedicated offset so identity numbering draws from an independent stream.
_IDENTITY_SEED_OFFSET = 540_054


def assign_identities(registry: Any, country: str, master_seed: int) -> None:
    """Assign insurance enrollment + national identity to every resident.

    No-op for countries without an `identity.yaml` (e.g. US in Phase 1), which keep
    their existing insurance handling.
    """
    config = load_identity_config(country)
    if not config:
        return

    provider = get_provider(country)
    rng = np.random.default_rng(master_seed + _IDENTITY_SEED_OFFSET)

    for household in registry.households:
        members = household.members
        if not members:
            continue
        enrollments = provider.assign_household(members, rng, config)
        household_latent = float(rng.standard_normal())  # shared draw → intra-household corr.
        for m in members:
            identity = provider.assign_personal(m, household_latent, rng, config)
            enrollment = enrollments.get(m.person_id)
            m.identity = IdentityTimeline(
                national=identity,
                enrollments=[enrollment] if enrollment is not None else [],
            )
