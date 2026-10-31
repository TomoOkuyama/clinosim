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

import yaml

from clinosim.codes.loader import display

_DATA_FILE = Path(__file__).parent / "data" / "clinosim-procedure-catalog.yaml"


@cache
def _catalog() -> dict[str, Any]:
    return yaml.safe_load(_DATA_FILE.read_text(encoding="utf-8")) or {}


def bedside_procedures() -> tuple[dict[str, Any], ...]:
    """Bedside / routine inpatient procedures in dispatch order."""
    return tuple(_catalog().get("bedside") or ())


@cache
def _entries() -> dict[str, dict[str, Any]]:
    return {str(e["type"]): e for e in bedside_procedures()}


def procedure_code(proc_type: str, country: str) -> str:
    """CPT (US) or K-code (JP) of a procedure type; ``""`` when the catalog has
    no verified code for it."""
    entry = _entries().get(proc_type) or {}
    field = "k_code" if str(country).strip().upper() == "JP" else "cpt"
    return str(entry.get(field) or "")


def procedure_type_display(proc_type: str, lang: str) -> str:
    """Name of a procedure type in ``lang`` (then English) from the catalog;
    an unknown type is humanised (underscores → spaces), never a raw slug."""
    if not proc_type:
        return ""
    entry = _entries().get(proc_type) or _entries().get(str(proc_type).strip().lower()) or {}
    names = entry.get("name") or {}
    return str(names.get(lang) or names.get("en") or str(proc_type).replace("_", " "))


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
