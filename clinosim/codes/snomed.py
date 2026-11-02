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

from clinosim.codes.loader import display
from clinosim.datafiles import load_data_yaml

__all__ = ["snomed_display", "snomed_for", "snomed_for_phrase", "snomed_map"]

_MAPS = Path(__file__).parent / "data" / "snomed-maps.yaml"


def snomed_display(code: str, lang: str = "en") -> str | None:
    """Display of a registered SNOMED CT code in ``lang`` (then English);
    ``None`` when the code is not registered."""
    return display("snomed-ct", code, lang) if code else None


@cache
def snomed_map(kind: str) -> dict[str, str]:
    """Internal key → SNOMED CT code for vocabulary ``kind`` (``route``,
    ``severity``). Raises ``KeyError`` on an unknown kind."""
    data = load_data_yaml(_MAPS)
    if kind not in data:
        raise KeyError(f"snomed_map: unknown kind {kind!r}; expected one of {sorted(data)}")
    return {str(k): str(v) for k, v in (data[kind] or {}).items()}


def snomed_for(kind: str, key: str) -> str | None:
    """SNOMED CT code for an internal ``key`` of vocabulary ``kind``; ``None``
    when the key has no code."""
    return snomed_map(kind).get(key)


_PHRASES = Path(__file__).parent / "data" / "procedure-phrase-to-snomed.yaml"


@cache
def _phrase_entries() -> tuple[tuple[str, str], ...]:
    data = load_data_yaml(_PHRASES)
    out = []
    for entry in data.get("entries") or []:
        match = str(entry.get("match") or "").strip().lower()
        code = str(entry.get("snomed") or "").strip()
        if match and code:
            out.append((match, code))
    return tuple(out)


def snomed_for_phrase(text: str) -> str | None:
    """SNOMED CT code of a free-text procedure / order name: the first
    ``codes/data/procedure-phrase-to-snomed.yaml`` entry whose phrase occurs in
    ``text`` (case-insensitive); ``None`` on a miss (Issue #2363)."""
    needle = (text or "").strip().lower() if isinstance(text, str) else ""
    if not needle:
        return None
    return next((code for match, code in _phrase_entries() if match in needle), None)
