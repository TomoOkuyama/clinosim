"""Country → IdentityProvider resolution (AD-54).

A provider registers itself with
``@register_implementation("identity_provider", name)`` and the country profile
(``locale/<cc>/country.yaml`` ``implementations.identity_provider``) selects it.
Add a country by naming a provider in its profile + adding
``locale/<cc>/identity.yaml``.
"""

from __future__ import annotations

from clinosim.countries import country_code
from clinosim.country_profile import implementation
from clinosim.modules.identity.base import IdentityProvider

_CACHE: dict[str, IdentityProvider] = {}


def get_provider(country: str) -> IdentityProvider:
    """Return the identity provider for a country code (ISO 3166-1 alpha-2,
    case-insensitive): the implementation the country profile names under
    ``identity_provider`` (Issue #3144). A country without a profile raises
    ``KeyError``.
    """
    key = country_code(country)
    if key not in _CACHE:
        _CACHE[key] = implementation("identity_provider", key)()
    return _CACHE[key]
