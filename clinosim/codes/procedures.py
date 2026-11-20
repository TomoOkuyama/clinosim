"""Procedure codes and names (Issue #2263).

The catalog (``codes/data/clinosim-procedure-catalog.yaml``) holds, per
procedure type, the CPT code (US), the 診療行為 K-code (JP) and the en/ja
name. Displays of a coded procedure come from the CPT / K-code registries.
"""

from __future__ import annotations

from collections.abc import Iterable
from functools import cache
from pathlib import Path
from typing import Any

from clinosim.codes.loader import display, system_key_for
from clinosim.datafiles import load_data_yaml

_DATA_FILE = Path(__file__).parent / "data" / "clinosim-procedure-catalog.yaml"

# Catalog field holding the code of each procedure code system (Issue #3144).
_CATALOG_FIELD = {"cpt": "cpt", "k-codes": "k_code"}


@cache
def _catalog() -> dict[str, Any]:
    return load_data_yaml(_DATA_FILE)


def bedside_procedures() -> tuple[dict[str, Any], ...]:
    """Bedside / routine inpatient procedures in dispatch order."""
    return tuple(_catalog().get("bedside") or ())


@cache
def _entries() -> dict[str, dict[str, Any]]:
    named = tuple(_catalog().get("named") or ())
    return {str(e["type"]): e for e in (*bedside_procedures(), *named)}


def catalog_procedure_types() -> frozenset[str]:
    """Every procedure type the catalog names: the bedside procedures and the
    ``named`` types recorded elsewhere (Issue #3081)."""
    return frozenset(_entries())


def procedure_code(proc_type: str, country: str) -> str:
    """CPT (US) or K-code (JP) of a procedure type — the catalog field of the
    country's procedure code system; ``""`` when the catalog has no verified
    code for it."""
    entry = _entries().get(proc_type) or {}
    field = _CATALOG_FIELD[system_key_for("procedure", country)]
    return str(entry.get(field) or "")


def country_procedure_code(country: str, codes: dict[str, Any]) -> Any:
    """The code, from ``codes`` keyed by procedure code-system key (``"cpt"``,
    ``"k-codes"``), of the system the country profile names for procedures
    (Issue #3144). The value is returned as given."""
    return codes[system_key_for("procedure", country)]


def procedure_anesthesia(proc_type: str) -> str:
    """Anesthesia under which the catalog says a procedure type is done
    (``none`` / ``local`` / ``sedation`` / ``general``); ``""`` (not recorded)
    when the catalog does not say (Issue #3257)."""
    return str((_entries().get(proc_type) or {}).get("anesthesia") or "")


def procedure_aftercare(proc_type: str) -> str:
    """Aftercare category of a procedure type (``urinary_catheter``,
    ``vascular_access``, ``surgical_wound`` ...), which selects the plan the
    operative / procedure note writes after it; ``""`` when the catalog does
    not say (Issue #3257). The text of each category is the
    ``procedure_aftercare.<category>`` phrase."""
    return str((_entries().get(proc_type) or {}).get("aftercare") or "")


def procedure_type_display(proc_type: str, lang: str) -> str:
    """Name of a procedure type in ``lang`` (then English) from the catalog;
    an unknown type is humanised (underscores → spaces), never a raw slug."""
    if not proc_type:
        return ""
    from clinosim.locale.localized import localized

    entry = _entries().get(proc_type) or _entries().get(str(proc_type).strip().lower()) or {}
    return localized(entry.get("name") or {}, lang, fallback=str(proc_type).replace("_", " "))


def procedure_code_display(codes: Iterable[str], lang: str) -> str | None:
    """Display of the first code that resolves, trying the K-code registry and
    then CPT for each code in turn; ``None`` when none resolves. The one copy
    of the "K-codes, then CPT" display loop."""
    for code in codes:
        if not code:
            continue
        for system_key in ("k-codes", "cpt"):
            hit = display(system_key, code, lang)
            if hit:
                return hit
    return None


def procedure_specimens(proc_type: str) -> tuple[str, ...]:
    """Specimens a procedure type removes and sends to histopathology, as
    ``specimen_type`` keys of ``snomed-maps.yaml`` (the catalog's
    ``specimens`` table, Issue #3284); empty for a procedure that sends none."""
    return tuple(str(s) for s in (_catalog().get("specimens") or {}).get(proc_type) or ())


def procedure_implants(proc_type: str) -> tuple[str, ...]:
    """Devices a procedure type leaves in the patient, as keys of
    ``narrative_op_implants.yaml`` (the catalog's ``implants`` table, Issue
    #3406); empty for a procedure that leaves none."""
    return tuple(str(i) for i in (_catalog().get("implants") or {}).get(proc_type) or ())


def specimen_code(slug: str) -> str:
    """SNOMED CT specimen concept of a ``specimens_sent`` entry; ``""`` when
    the key is not mapped (Issue #3284)."""
    from clinosim.codes.snomed import snomed_for

    return snomed_for("specimen_type", slug) or "" if slug else ""


def specimen_label(slug: str, lang: str) -> str:
    """Clinical label of a ``specimens_sent`` entry in ``lang`` (then English):
    the ``surgical_specimen`` narrative label ("Appendix" / 虫垂), else the
    SNOMED CT display of its specimen concept. The operative note's specimen
    line and FHIR ``Specimen.type.text`` (Issue #3284)."""
    from clinosim.locale.loader import narrative_label

    code = specimen_code(slug)
    fallback = (display("snomed-ct", code, lang) if code else None) or slug.replace("_", " ")
    return narrative_label("surgical_specimen", slug, lang, fallback=fallback)
