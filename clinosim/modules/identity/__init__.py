"""Resident identifier & insurance numbering module (AD-54).

Country-pluggable: `get_provider(country)` resolves the numbering rules;
`assign_identities(...)` runs the post-population numbering pass.
"""

from clinosim.modules.identity.assign import assign_identities
from clinosim.modules.identity.registry import get_provider

__all__ = ["get_provider", "assign_identities"]
