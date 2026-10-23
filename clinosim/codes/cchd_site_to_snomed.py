"""CCHD screening-site → SNOMED CT concept resolver (#1815 fix, Phase 3.β.5).

Mirrors Phase 3.β.2/3/4/6:
``clinosim/codes/data/cchd-site-to-snomed.yaml`` holds the internal
CCHD screening site → SNOMED CT body-site pointers; this module is
the loader that ``modules/newborn/fhir_emit.py`` uses in place of the
retired module-local ``_CCHD_SITE_SNOMED`` dict (which carried
left-sided SNOMED codes for right-sided clinical measurements —
#1815).

The SNOMED display is still resolved via
``clinosim.codes.lookup("snomed-ct", code, lang)`` against the authority
yaml — this catalog carries only the pointer, keeping the display SoT
in ``snomed-ct.yaml``.
"""

from __future__ import annotations

from functools import cache
from pathlib import Path

import yaml

_DATA_FILE = Path(__file__).parent / "data" / "cchd-site-to-snomed.yaml"


@cache
def _load_catalog() -> dict[str, str]:
    """Load the CCHD-site → SNOMED code mapping. Fail-loud on missing
    file — downstream FHIR Observation.bodySite coding depends on it."""
    if not _DATA_FILE.exists():
        raise FileNotFoundError(f"cchd-site-to-snomed.yaml not found at {_DATA_FILE}")
    with _DATA_FILE.open(encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    sites = raw.get("sites") or {}
    if not isinstance(sites, dict):
        raise ValueError(f"cchd-site-to-snomed.yaml: 'sites' must be a mapping, got {type(sites).__name__}")
    return {str(k): str(v) for k, v in sites.items() if v}


def resolve_cchd_site_snomed(site: str) -> str | None:
    """Return the SNOMED CT concept id for CCHD screening ``site``, or
    None when the site has no catalog entry. The None return keeps
    the FHIR emitter's existing silent-skip behaviour for unknown
    values."""
    if not site:
        return None
    return _load_catalog().get(site)


def all_cchd_sites() -> tuple[str, ...]:
    """Return every registered CCHD screening site (sorted). Used by
    integrity tests + audit scripts."""
    return tuple(sorted(_load_catalog().keys()))
