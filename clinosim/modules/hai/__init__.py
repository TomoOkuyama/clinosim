"""AD-55 Module: hai — HAI onset sampling (CLABSI / CAUTI / VAP)."""
from __future__ import annotations

from clinosim.modules.hai.engine import (
    load_hai_codes,
    load_hai_organisms,
    load_hai_rates,
    load_hai_specimens,
    sample_hai_onset,
)

__all__ = [
    "load_hai_rates",
    "load_hai_codes",
    "load_hai_organisms",
    "load_hai_specimens",
    "sample_hai_onset",
]
