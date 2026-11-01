"""SNOMED CT accessor — displays and internal-key → code maps (Issue #2258).

Every SNOMED code clinosim emits is registered in ``codes/data/snomed-ct.yaml``
with an English display (the SNOMED International preferred term, verified on
tx.fhir.org ``$lookup``) and, where needed, a Japanese label. Vocabularies that
map an internal key to a code (order route, condition severity) are code-only
tables in ``codes/data/snomed-maps.yaml``. Emitters build codings from these
with ``dual_slot_concept("snomed-ct", code, lang)`` instead of holding codes
and displays of their own.
"""

from __future__ import annotations

from functools import cache
from pathlib import Path

import yaml

from clinosim.codes.loader import display

__all__ = ["snomed_display", "snomed_for", "snomed_map"]

_MAPS = Path(__file__).parent / "data" / "snomed-maps.yaml"


def snomed_display(code: str, lang: str = "en") -> str | None:
    """Display of a registered SNOMED CT code in ``lang`` (then English);
    ``None`` when the code is not registered."""
    return display("snomed-ct", code, lang) if code else None


@cache
def snomed_map(kind: str) -> dict[str, str]:
    """Internal key → SNOMED CT code for vocabulary ``kind`` (``route``,
    ``severity``). Raises ``KeyError`` on an unknown kind."""
    data = yaml.safe_load(_MAPS.read_text(encoding="utf-8")) or {}
    if kind not in data:
        raise KeyError(f"snomed_map: unknown kind {kind!r}; expected one of {sorted(data)}")
    return {str(k): str(v) for k, v in (data[kind] or {}).items()}


def snomed_for(kind: str, key: str) -> str | None:
    """SNOMED CT code for an internal ``key`` of vocabulary ``kind``; ``None``
    when the key has no code."""
    return snomed_map(kind).get(key)
