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
