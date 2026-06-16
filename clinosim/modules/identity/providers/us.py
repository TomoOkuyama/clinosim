"""US identity provider (AD-54) — thin Phase-1 stub.

US insurance handling currently lives in `patient/activator.py:_sample_insurance`
and is intentionally left untouched in Phase 1 (behavior-compat). This provider
exists for registry/abstraction completeness; Phase 4 migrates the US logic here.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from clinosim.types import InsuranceEnrollment, NationalIdentity


class USIdentityProvider:
    country = "US"

    def assign_household(
        self,
        members: list[Any],
        rng: np.random.Generator,
        config: dict[str, Any],
    ) -> dict[str, InsuranceEnrollment]:
        return {}

    def assign_personal(
        self,
        member: Any,
        household_latent: float,
        rng: np.random.Generator,
        config: dict[str, Any],
    ) -> NationalIdentity:
        return NationalIdentity(country="US")
