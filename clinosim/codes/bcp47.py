"""IETF BCP 47 language-tag accessor (Issue #2481).

The registry (``codes/data/bcp-47-language.yaml``) keeps the IETF canonical
display under ``en``. A profile family whose validator registers a different
string keeps it in the file's ``profile_displays`` block, so the variant is
chosen by profile, never by passing a non-language key as ``lang``.
"""

from __future__ import annotations

from functools import cache
from pathlib import Path

from clinosim.codes.loader import display
from clinosim.datafiles import load_data_yaml

__all__ = ["bcp47_display"]

_DATA = Path(__file__).parent / "data" / "bcp-47-language.yaml"


@cache
def _profile_displays() -> dict[str, dict[str, str]]:
    raw = load_data_yaml(_DATA)
    block = raw.get("profile_displays") or {}
    return {str(p): {str(k): str(v) for k, v in (rows or {}).items()} for p, rows in block.items()}


def bcp47_display(tag: str, *, profile: str | None = None) -> str | None:
    """English display of a BCP 47 tag: the ``profile`` family's registered
    variant when it has one, else the IETF canonical display; ``None`` when
    the tag is not registered."""
    if profile:
        variant = _profile_displays().get(profile, {}).get(tag)
        if variant:
            return variant
    return display("bcp-47-language", tag, "en")
