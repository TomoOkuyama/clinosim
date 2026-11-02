"""MEDIS accessor — 標準病名マスター 病名管理番号 (code-mapping spec §2.2,
Issue #2463).

The verified seed crosswalk ICD-10 → MEDIS 病名管理番号 lives in
``codes/data/medis-disease-keyno.yaml``; ``clinosim.codes.icd10`` re-exports
``medis_disease_keyno`` for existing callers.
"""

from __future__ import annotations

from functools import cache
from pathlib import Path

from clinosim.datafiles import load_data_yaml

__all__ = ["medis_disease_keyno"]

_MEDIS_CROSSWALK = Path(__file__).parent / "data" / "medis-disease-keyno.yaml"


@cache
def _medis_crosswalk() -> dict[str, tuple[str, str]]:
    if not _MEDIS_CROSSWALK.exists():
        return {}
    data = load_data_yaml(_MEDIS_CROSSWALK)
    out: dict[str, tuple[str, str]] = {}
    for icd, entry in (data.get("crosswalk") or {}).items():
        if not isinstance(entry, dict):
            continue
        code = str(entry.get("medis_code") or "").strip()
        name = str(entry.get("medis_display") or "").strip()
        if code and name:
            out[str(icd).strip()] = (code, name)
    return out


def medis_disease_keyno(icd_code: str) -> tuple[str, str] | None:
    """MEDIS 標準病名マスター 病名管理番号 ``(code, display)`` for an ICD-10 code:
    the exact code, then its 3-character category; ``None`` when the
    verified seed crosswalk has no entry (Issue #1277)."""
    if not icd_code:
        return None
    crosswalk = _medis_crosswalk()
    hit = crosswalk.get(icd_code)
    if hit is not None:
        return hit
    base = icd_code.split(".")[0]
    return crosswalk.get(base) if base != icd_code else None
