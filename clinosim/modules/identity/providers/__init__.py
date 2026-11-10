"""Country-specific identity providers (AD-54). The JP provider is in
``clinosim/countries/jp/identity_provider.py`` (Issue #3194)."""

from clinosim.modules.identity.providers.us import USIdentityProvider

__all__ = ["USIdentityProvider"]
