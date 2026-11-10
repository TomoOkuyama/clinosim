"""JP drug code system by code format (``drug_system`` "jp_code_format",
Issue #3144): the JP drug code family (YJ, HOT7 / HOT9 / HOT13) read from the
code's shape (:func:`clinosim.codes.yj.jp_drug_system_key`)."""

from __future__ import annotations

from clinosim.codes.yj import jp_drug_system_key
from clinosim.country_profile import register_implementation


@register_implementation("drug_system", "jp_code_format")
def jp_drug_system(code: str, country: str) -> str:
    """The JP drug code family of ``code``."""
    return jp_drug_system_key(code)
