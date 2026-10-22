"""Encounter-type → SNOMED CT concept resolver (Phase 3.β.4, #1808 follow-up).

Mirrors Phase 3.β.2/3/6:
``clinosim/codes/data/encounter-type-to-snomed.yaml`` holds the
internal encounter-type → SNOMED code pointers; this module is the
loader that ``fhir_r4/encounters/encounter.py`` uses in place of the
retired module-local ``_ENCOUNTER_TYPE_SNOMED_CODE`` dict in
``fhir_r4/lib/reference_data.py``.

The SNOMED display is still resolved via
``clinosim.codes.lookup("snomed-ct", code, lang)`` against the authority
yaml — this catalog carries only the pointer, keeping the display SoT
in ``snomed-ct.yaml``.
"""

from __future__ import annotations

from functools import cache
from pathlib import Path

import yaml

_DATA_FILE = Path(__file__).parent / "data" / "encounter-type-to-snomed.yaml"


@cache
def _load_catalog() -> dict[str, str]:
    """Load the encounter-type → SNOMED code mapping. Fail-loud on
    missing file — downstream FHIR Encounter.type coding depends on it."""
    if not _DATA_FILE.exists():
        raise FileNotFoundError(f"encounter-type-to-snomed.yaml not found at {_DATA_FILE}")
    with _DATA_FILE.open(encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    types = raw.get("encounter_types") or {}
    if not isinstance(types, dict):
        raise ValueError(
            f"encounter-type-to-snomed.yaml: 'encounter_types' must be a mapping, got {type(types).__name__}"
        )
    return {str(k): str(v) for k, v in types.items() if v}


def resolve_encounter_type_snomed(enc_type: str) -> str | None:
    """Return the SNOMED CT concept id for encounter-type ``enc_type``,
    or None when the type has no catalog entry.

    The None return keeps the FHIR emitter's existing silent-skip
    behaviour for unknown values."""
    if not enc_type:
        return None
    return _load_catalog().get(enc_type)


def all_encounter_types() -> tuple[str, ...]:
    """Return every registered encounter-type (sorted). Used by
    integrity tests + audit scripts."""
    return tuple(sorted(_load_catalog().keys()))
