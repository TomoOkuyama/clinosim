"""ICD-10 accessor — diagnosis code system, display names and the MEDIS crosswalk (Issue #2257).

Internal diagnosis codes are ICD-10-CM (AD-30); the output code system is
ICD-10-CM for the US and the MHLW ICD-10 (``icd-10-mhlw``, same data as WHO
``icd-10``) for JP. Every consumer resolves the system, the official display,
the clinical short name and the MEDIS 病名管理番号 through these functions
instead of re-coding the country choice or reading the data YAMLs.

Display resolution follows :func:`clinosim.codes.loader.display`: exact, base
and child codes in the system, then its declared sibling (``icd-10`` /
``icd-10-mhlw`` ↔ ``icd-10-cm``), in ``lang`` then English. A miss is ``None``.
"""

from __future__ import annotations

from functools import cache
from pathlib import Path

import yaml

from clinosim.codes.loader import display, system_key_for

__all__ = [
    "condition_label",
    "condition_short_name",
    "icd10_display",
    "icd10_system",
    "medis_disease_keyno",
]

_MEDIS_CROSSWALK = Path(__file__).parent / "data" / "medis-disease-keyno.yaml"


def icd10_system(country: str) -> str:
    """Registry key of the ICD-10 system a country emits: ``icd-10-cm`` (US),
    ``icd-10-mhlw`` (JP)."""
    return system_key_for("diagnosis", country)


def icd10_display(code: str, country: str, lang: str) -> str | None:
    """Official display of ``code`` in the country's ICD-10 system, in ``lang``
    (then English); ``None`` when the code is not registered."""
    return display(icd10_system(country), code, lang) if code else None


def condition_short_name(code: str, lang: str) -> str | None:
    """Clinical short name of a diagnosis (``COPD``, 「高血圧」), keyed by the
    3-character ICD-10 category shared by ICD-10-CM and WHO ICD-10
    (``codes/data/condition-short-name.yaml``); ``None`` when the category has
    no short name."""
    base = (code or "").split(".")[0]
    return display("condition-short-name", base, lang) if base else None


def condition_label(code: str, country: str, lang: str) -> str | None:
    """Name of a diagnosis in prose and in ``Condition.code.text``: the clinical
    short name, then the official display; ``None`` when neither exists.
    Narrative and the FHIR Condition use the same label (Issue #2360)."""
    return condition_short_name(code, lang) or icd10_display(code, country, lang)


@cache
def _medis_crosswalk() -> dict[str, tuple[str, str]]:
    if not _MEDIS_CROSSWALK.exists():
        return {}
    data = yaml.safe_load(_MEDIS_CROSSWALK.read_text(encoding="utf-8")) or {}
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
