"""Country-pluggable identity provider interface (AD-54).

`IdentityProvider` is the seam for adding countries: implement it + add a
`locale/<cc>/identity.yaml`, with no engine changes (same philosophy as
disease/encounter YAMLs).

`ResidentLike` is a structural type so this module never imports `population`
(module-independence rule: identity depends only on types/locale/codes).
"""

from __future__ import annotations

from datetime import date
from typing import Any, Protocol, runtime_checkable

import numpy as np

from clinosim.types import InsuranceEnrollment, NationalIdentity


@runtime_checkable
class ResidentLike(Protocol):
    """Structural view of a Layer-1 resident needed for numbering."""

    person_id: str
    household_id: str
    age: int
    sex: str
    date_of_birth: date
    occupation: str


class IdentityProvider(Protocol):
    """Per-country numbering rules."""

    country: str

    def assign_household(
        self,
        members: list[Any],
        rng: np.random.Generator,
        config: dict[str, Any],
    ) -> dict[str, InsuranceEnrollment]:
        """Assign insurance enrollment to each household member (keyed by person_id).

        Shares group symbol / member id per the country's scheme rules and gives each
        member a branch number; per-individual schemes (e.g. 後期高齢者) get their own.
        """
        ...

    def assign_personal(
        self,
        member: Any,
        household_latent: float,
        rng: np.random.Generator,
        config: dict[str, Any],
    ) -> NationalIdentity:
        """Assign per-individual national-identity attributes (e.g. card holding).

        `household_latent` is a shared N(0,1) draw enabling intra-household
        correlation while preserving the marginal age-banded rates.
        """
        ...
