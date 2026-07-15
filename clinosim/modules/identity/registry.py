"""Country → IdentityProvider resolution (AD-54).

Mirrors the `healthcare_system` country-config pattern. Add a country by
registering a provider here + adding `locale/<cc>/identity.yaml`.
"""

from __future__ import annotations

from clinosim.modules._shared import is_jp, is_us
from clinosim.modules.identity.base import IdentityProvider
from clinosim.modules.identity.providers import JPIdentityProvider, USIdentityProvider

_SUPPORTED = {"JP", "US"}
_CACHE: dict[str, IdentityProvider] = {}


def get_provider(country: str) -> IdentityProvider:
    """Return the identity provider for a country code (ISO 3166-1 alpha-2).

    Case-insensitive via the canonical is_jp/is_us predicates — a raw
    ``country == "JP"`` comparison would raise on a lowercase ``"jp"`` that
    production passes unnormalized (FP-UNIFY-4 sibling class).
    """
    if is_jp(country):
        key = "JP"
    elif is_us(country):
        key = "US"
    else:
        raise ValueError(f"Unsupported country: {country}. Supported: {sorted(_SUPPORTED)}")
    if key not in _CACHE:
        _CACHE[key] = JPIdentityProvider() if key == "JP" else USIdentityProvider()
    return _CACHE[key]
