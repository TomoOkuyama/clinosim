"""AD-55 Module: hai — HAI onset sampling (CLABSI / CAUTI / VAP)."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

from clinosim.modules.hai.engine import (
    load_hai_codes,
    load_hai_organisms,
    load_hai_rates,
    load_hai_specimens,
    sample_hai_onset,
)
from clinosim.modules.hai.enricher import enrich_hai

# Canonical lowercase hai_type strings. These MUST be used everywhere a
# hai_type appears (HAIEvent construction, YAML key, lift table lookup, tests).
# The earlier mismatch (UPPERCASE YAML keys + lowercase enricher writes)
# silently no-op'd the entire Phase 3a lift in production; a YAML integrity
# test plus this single source of truth prevents that class of regression.
HAI_TYPES: tuple[str, ...] = ("clabsi", "cauti", "vap")

_HAI_REF_DIR = Path(__file__).parent / "reference_data"
_HAI_ANTIBIOGRAM_PATH = _HAI_REF_DIR / "hai_antibiogram.yaml"
_HAI_ORGANISMS_PATH = _HAI_REF_DIR / "hai_organisms.yaml"


def _organisms_by_hai_type() -> dict[str, set[str]]:
    with open(_HAI_ORGANISMS_PATH) as f:
        data = yaml.safe_load(f) or {}
    table = data.get("hai_organisms") or {}
    return {
        hai_type: {str(entry["snomed"]) for entry in entries}
        for hai_type, entries in table.items()
    }


@lru_cache(maxsize=1)
def load_hai_antibiogram() -> dict:  # type: ignore[type-arg]
    """Load and validate hai_antibiogram.yaml.

    Validates at import time so a typo (uppercase hai_type, unknown organism,
    unknown antibiotic, malformed probability triple) raises ValueError loudly
    instead of silently producing a no-op antibiogram lookup at runtime.
    Lesson from PR-90 silent no-op (xhigh review).
    """
    from clinosim.modules.antibiotic import ANTIBIOTIC_LOINC_LOOKUP

    with open(_HAI_ANTIBIOGRAM_PATH) as f:
        raw = yaml.safe_load(f) or {}
    abg = raw.get("hai_antibiogram") or {}
    valid_hai_types = set(HAI_TYPES)
    valid_organisms = _organisms_by_hai_type()
    valid_antibiotics = set(ANTIBIOTIC_LOINC_LOOKUP.keys())

    for hai_type, organisms in abg.items():
        if hai_type not in valid_hai_types:
            raise ValueError(
                f"hai_antibiogram.yaml: unknown hai_type {hai_type!r}, "
                f"expected one of {sorted(valid_hai_types)}"
            )
        for snomed, abx_table in organisms.items():
            allowed_snomeds = valid_organisms.get(hai_type, set())
            if snomed not in allowed_snomeds:
                raise ValueError(
                    f"hai_antibiogram.yaml: organism {snomed!r} not in "
                    f"hai_organisms.yaml for hai_type {hai_type!r}"
                )
            for abx_key, triple in abx_table.items():
                if abx_key not in valid_antibiotics:
                    raise ValueError(
                        f"hai_antibiogram.yaml: unknown antibiotic key "
                        f"{abx_key!r} (must be one of ANTIBIOTIC_LOINC_LOOKUP)"
                    )
                if not isinstance(triple, list) or len(triple) != 3:
                    raise ValueError(
                        f"hai_antibiogram.yaml: triple for {hai_type}/{snomed}/"
                        f"{abx_key} must be length 3, got {triple!r}"
                    )
                if abs(sum(triple) - 1.0) > 0.01:
                    raise ValueError(
                        f"hai_antibiogram.yaml: triple for {hai_type}/{snomed}/"
                        f"{abx_key} must sum to ~1.0, got {sum(triple):.3f}"
                    )
    return abg


__all__ = [
    "HAI_TYPES",
    "load_hai_antibiogram",
    "load_hai_rates",
    "load_hai_codes",
    "load_hai_organisms",
    "load_hai_specimens",
    "sample_hai_onset",
    "enrich_hai",
]
