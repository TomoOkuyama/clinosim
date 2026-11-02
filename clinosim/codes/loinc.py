"""LOINC display and coding (Issue #2260).

Displays come from ``codes/data/loinc.yaml``; every entry's ``en`` is the LOINC
display verified against loinc.org / tx.fhir.org (spec §7). LOINC is an
English-only CodeSystem: on JP output the coding keeps the English display and
the Japanese label goes in ``CodeableConcept.text`` (spec §5.3).
"""

from __future__ import annotations

from functools import cache
from pathlib import Path
from typing import Any

from clinosim.codes.loader import display, get_system_uri
from clinosim.datafiles import load_data_yaml

_MAPS = Path(__file__).parent / "data" / "loinc-maps.yaml"


@cache
def loinc_map(kind: str) -> dict[str, str]:
    """Internal key → LOINC code for vocabulary ``kind`` (``loinc-maps.yaml``,
    Issue #2392). Raises ``KeyError`` on an unknown kind."""
    data = load_data_yaml(_MAPS)
    if kind not in data:
        raise KeyError(f"loinc_map: unknown kind {kind!r}; expected one of {sorted(data)}")
    return {str(k): str(v) for k, v in (data[kind] or {}).items()}


def loinc_for(kind: str, key: str) -> str:
    """LOINC code for an internal ``key`` of vocabulary ``kind``. Raises
    ``KeyError`` on an unknown key: every emitted key is mapped."""
    return loinc_map(kind)[str(key)]


def loinc_display(code: str, lang: str) -> str | None:
    """Display of a LOINC code in ``lang`` (then English); ``None`` when the
    code is not registered."""
    return display("loinc", code, lang)


def loinc_coding(code: str, lang: str) -> dict[str, Any]:
    """A LOINC ``Coding``; the display is omitted when the code is not
    registered (never the code itself)."""
    entry: dict[str, Any] = {"system": get_system_uri("loinc"), "code": code}
    disp = loinc_display(code, lang)
    if disp:
        entry["display"] = disp
    return entry
