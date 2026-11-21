"""Repeat draw after a hemolyzed specimen (Issue #3452).

A hemolyzed potassium (flag ``H*`` / ``L*``) reads falsely high, so it is
neither a hyperkalemia trigger nor a treatment value; the lab repeats the
draw. Rules live in ``reference_data/hemolysis_redraw.yaml``.
"""

from __future__ import annotations

import functools
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from clinosim.datafiles import load_data_yaml

HEMOLYZED_FLAGS: frozenset[str] = frozenset({"H*", "L*"})
"""Result flags that mark a hemolyzed specimen (the canonical set; the
pipeline writes ``H*``, ``L*`` is kept for a low-side hemolysis flag)."""

_YAML = Path(__file__).resolve().parent / "reference_data" / "hemolysis_redraw.yaml"


class HemolysisRedrawRules(BaseModel):
    """Shape of ``hemolysis_redraw.yaml``."""

    model_config = ConfigDict(extra="forbid")
    labs: list[str] = Field(min_length=1)
    delay_minutes: int = Field(gt=0, le=120)
    max_redraws: int = Field(ge=1, le=10)


@functools.cache
def hemolysis_redraw_rules() -> HemolysisRedrawRules:
    """The validated repeat-draw rules."""
    return HemolysisRedrawRules.model_validate(load_data_yaml(_YAML))


def is_hemolyzed(flag: object) -> bool:
    """True when a result flag marks a hemolyzed specimen."""
    return str(flag or "") in HEMOLYZED_FLAGS
