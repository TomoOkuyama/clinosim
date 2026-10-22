"""Blood-group key → SNOMED CT concept resolver (Phase 3.β.2, #1808 follow-up).

Mirrors Phase 3.β.6 ``stage_to_snomed``:
``clinosim/codes/data/blood-group-to-snomed.yaml`` holds the internal
ABO letter / Rh glyph → SNOMED code pointers; this module is the loader
that ``fhir_r4/labs/blood_type.py`` uses in place of the retired
module-local ``_SNOMED_ABO_BY_TYPE`` / ``_SNOMED_RH_BY_FACTOR`` dicts.

The SNOMED display is still resolved via
``clinosim.codes.lookup("snomed-ct", code, lang)`` against the authority
yaml — this catalog carries only the pointer, keeping the display SoT
in ``snomed-ct.yaml``.
"""

from __future__ import annotations

from functools import cache
from pathlib import Path

import yaml

_DATA_FILE = Path(__file__).parent / "data" / "blood-group-to-snomed.yaml"


@cache
def _load_catalog() -> dict[str, dict[str, str]]:
    """Load the ABO + Rh key → SNOMED code mappings. Fail-loud on
    missing file — downstream FHIR Observation.valueCodeableConcept
    coding depends on it."""
    if not _DATA_FILE.exists():
        raise FileNotFoundError(f"blood-group-to-snomed.yaml not found at {_DATA_FILE}")
    with _DATA_FILE.open(encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    abo = raw.get("abo") or {}
    rh = raw.get("rh") or {}
    if not isinstance(abo, dict):
        raise ValueError(f"blood-group-to-snomed.yaml: 'abo' must be a mapping, got {type(abo).__name__}")
    if not isinstance(rh, dict):
        raise ValueError(f"blood-group-to-snomed.yaml: 'rh' must be a mapping, got {type(rh).__name__}")
    return {
        "abo": {str(k): str(v) for k, v in abo.items() if v},
        "rh": {str(k): str(v) for k, v in rh.items() if v},
    }


def resolve_abo_snomed(abo_type: str) -> str | None:
    """Return the SNOMED CT concept id for ABO letter ``abo_type``, or
    None when the letter has no catalog entry. The None return keeps the
    FHIR emitter's existing silent-skip behaviour for unknown values."""
    if not abo_type:
        return None
    return _load_catalog()["abo"].get(abo_type)


def resolve_rh_snomed(rh_factor: str) -> str | None:
    """Return the SNOMED CT concept id for Rh factor ``rh_factor``
    (``+`` / ``-`` / ``positive`` / ``negative``), or None when the
    glyph has no catalog entry."""
    if not rh_factor:
        return None
    return _load_catalog()["rh"].get(rh_factor)


def all_abo_keys() -> tuple[str, ...]:
    """Return every registered ABO letter (sorted). Used by integrity
    tests + audit scripts."""
    return tuple(sorted(_load_catalog()["abo"].keys()))


def all_rh_keys() -> tuple[str, ...]:
    """Return every registered Rh glyph (sorted). Used by integrity
    tests + audit scripts."""
    return tuple(sorted(_load_catalog()["rh"].keys()))
