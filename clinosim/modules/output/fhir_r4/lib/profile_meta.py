"""``meta.profile`` a builder declares for the FHIR profiles a country applies
(Issue #3145).

``docs/design-guides/country-profile-spec.md`` §5: whether a profile's
structure is emitted is decided by the country profile
(``profile.uses(name)``); the profile URLs are data, read from
``clinosim/codes/data/fhir-profiles-<name>.yaml`` (``profiles``: resource type
→ URL list), the same tables the post-process profile stacking reads.
"""

from __future__ import annotations

from functools import cache
from typing import Any

from clinosim.codes import data_table
from clinosim.country_profile import country_profile


@cache
def _profile_urls(fhir_profile: str) -> dict[str, tuple[str, ...]]:
    raw = data_table(f"fhir-profiles-{fhir_profile.replace('_', '-')}")
    return {str(rt): tuple(str(u) for u in urls) for rt, urls in (raw.get("profiles") or {}).items()}


def declared_profiles(resource_type: str, country: str, *fhir_profiles: str) -> list[str]:
    """The profile URLs of ``resource_type`` for those of ``fhir_profiles`` that
    ``country``'s output applies, in the order given (a new list each call)."""
    profile = country_profile(country)
    return [url for name in fhir_profiles if profile.uses(name) for url in _profile_urls(name).get(resource_type, ())]


def profile_meta(resource_type: str, country: str, *fhir_profiles: str) -> dict[str, Any]:
    """``{"meta": {"profile": [...]}}`` for ``resource_type`` under
    ``fhir_profiles`` (default: JP Core) when the country applies any of them,
    else ``{}`` — spread into a resource literal where ``meta`` belongs."""
    urls = declared_profiles(resource_type, country, *(fhir_profiles or ("jp_core",)))
    return {"meta": {"profile": urls}} if urls else {}
