"""LOINC display and coding (Issue #2260).

Displays come from ``codes/data/loinc.yaml``; every entry's ``en`` is the LOINC
display verified against loinc.org / tx.fhir.org (spec §7). LOINC is an
English-only CodeSystem: on JP output the coding keeps the English display and
the Japanese label goes in ``CodeableConcept.text`` (spec §5.3).
"""

from __future__ import annotations

from typing import Any

from clinosim.codes.loader import display, get_system_uri


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
