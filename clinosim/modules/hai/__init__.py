"""AD-55 Module: hai — HAI onset sampling (CLABSI / CAUTI / VAP)."""
from __future__ import annotations

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

__all__ = [
    "HAI_TYPES",
    "load_hai_rates",
    "load_hai_codes",
    "load_hai_organisms",
    "load_hai_specimens",
    "sample_hai_onset",
    "enrich_hai",
]
