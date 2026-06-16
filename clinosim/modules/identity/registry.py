"""Country → IdentityProvider resolution (AD-54).

Mirrors the `healthcare_system` country-config pattern. Add a country by
registering a provider here + adding `locale/<cc>/identity.yaml`.
"""

from __future__ import annotations

from clinosim.modules.identity.base import IdentityProvider
from clinosim.modules.identity.providers import JPIdentityProvider, USIdentityProvider

_SUPPORTED = {"JP", "US"}
_CACHE: dict[str, IdentityProvider] = {}


def get_provider(country: str) -> IdentityProvider:
    """Return the identity provider for a country code (ISO 3166-1 alpha-2)."""
    if country not in _CACHE:
        if country == "JP":
            _CACHE[country] = JPIdentityProvider()
        elif country == "US":
            _CACHE[country] = USIdentityProvider()
        else:
            raise ValueError(
                f"Unsupported country: {country}. Supported: {sorted(_SUPPORTED)}"
            )
    return _CACHE[country]
