"""Country-specific identity providers (AD-54)."""

from clinosim.modules.identity.providers.jp import JPIdentityProvider
from clinosim.modules.identity.providers.us import USIdentityProvider

__all__ = ["JPIdentityProvider", "USIdentityProvider"]
