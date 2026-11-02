"""JLAC10 / JP-CLINS lab accessor (code-mapping spec §2.2, Issue #2463).

The JP lab CodeSystems (JP-CLINS core / infection labo, JLAC10 / JLAC11,
uncoded and local codes, the 17-digit JLAC10 and the specimen-material
system) by kind, and JLAC10 analyte displays.
"""

from __future__ import annotations

from clinosim.codes.loader import display, get_system_uri

__all__ = ["jlac10_display", "jp_clins_lab_system"]

_JP_CLINS_LAB_SYSTEM_KEYS: dict[str, str] = {
    "corelabo_jlac10": "jp-clins-lab-corelabo-jlac10",
    "corelabo_jlac11": "jp-clins-lab-corelabo-jlac11",
    "infectionlabo_jlac10": "jp-clins-lab-infectionlabo-jlac10",
    "infectionlabo_jlac11": "jp-clins-lab-infectionlabo-jlac11",
    "uncoded": "jp-clins-lab-uncoded",
    "localcode": "jp-clins-lab-localcode",
    "jlac10_17digits": "jlac10-17digits",
    "specimen_material": "jp-specimen-material-jlac10",
}


def jp_clins_lab_system(kind: str) -> str:
    """URI of a JP lab CodeSystem by kind (``corelabo_jlac10``, ``uncoded``,
    ``localcode``, ``jlac10_17digits``, ``specimen_material``, ...); KeyError
    on an unknown kind (Issue #2261)."""
    return get_system_uri(_JP_CLINS_LAB_SYSTEM_KEYS[kind])


def jlac10_display(code: str, lang: str) -> str | None:
    """Display of a JLAC10 analyte code in ``lang`` (then English); ``None``
    when the code is not registered (Issue #2261)."""
    return display("jlac10", code, lang)
