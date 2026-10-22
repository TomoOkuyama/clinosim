"""Stage-label → SNOMED CT concept resolver (Phase 3.β.6, #1808 follow-up).

Mirrors the META #1792 / `clinosim.codes.drugs` catalog pattern:
``clinosim/codes/data/clinosim-stage-to-snomed.yaml`` holds the
internal clinical-stage label → SNOMED code pointers; this module is
the loader that downstream callers (currently
``fhir_r4/conditions/conditions.py``) use instead of a module-local
dict.

The SNOMED display is still resolved via
``clinosim.codes.lookup("snomed-ct", code, lang)`` against the
authority yaml — this catalog carries only the pointer, keeping the
display SoT in ``snomed-ct.yaml``.
"""

from __future__ import annotations

from functools import cache
from pathlib import Path

import yaml

_DATA_FILE = Path(__file__).parent / "data" / "clinosim-stage-to-snomed.yaml"


@cache
def _load_catalog() -> dict[str, str]:
    """Load the stage-label → SNOMED CT concept mapping. Fail-loud on
    missing file — downstream FHIR Condition.stage.summary coding
    depends on it."""
    if not _DATA_FILE.exists():
        raise FileNotFoundError(f"clinosim-stage-to-snomed.yaml not found at {_DATA_FILE}")
    with _DATA_FILE.open(encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    stages = raw.get("stages") or {}
    if not isinstance(stages, dict):
        raise ValueError(f"clinosim-stage-to-snomed.yaml: 'stages' must be a mapping, got {type(stages).__name__}")
    return {str(k): str(v) for k, v in stages.items() if v}


def resolve_stage_snomed(stage_label: str) -> str | None:
    """Return the SNOMED CT concept id for ``stage_label``, or None
    when the label has no catalog entry (e.g. a cancer stage or a
    free-text severity that was not registered in the ladder).

    A None return is the signal for the FHIR emitter to omit the
    ``summary.coding`` field and keep ``summary.text`` only — same
    behaviour the retired ``_STAGE_SUMMARY_SNOMED.get(label)`` had.
    """
    if not stage_label:
        return None
    return _load_catalog().get(stage_label)


def all_stage_labels() -> tuple[str, ...]:
    """Return every registered stage label (sorted). Used by
    integrity tests + audit scripts."""
    return tuple(sorted(_load_catalog().keys()))
