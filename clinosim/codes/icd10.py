"""ICD-10 accessor — diagnosis code system, display names and the MEDIS crosswalk (Issue #2257).

Internal diagnosis codes are ICD-10-CM (AD-30); the output code system is
ICD-10-CM for the US and the MHLW ICD-10 (``icd-10-mhlw``, same data as WHO
``icd-10``) for JP. Every consumer resolves the system, the official display,
the clinical short name and the MEDIS 病名管理番号 through these functions
instead of re-coding the country choice or reading the data YAMLs.

Display resolution follows :func:`clinosim.codes.loader.display`: exact code,
its category (:class:`Icd10CodeSystem`) in the system, then its declared sibling (``icd-10`` /
``icd-10-mhlw`` ↔ ``icd-10-cm``), in ``lang`` then English. A miss is ``None``.
"""

from __future__ import annotations

from clinosim.codes.loader import CodeSystem, display, system_key_for
from clinosim.codes.medis import medis_disease_keyno as medis_disease_keyno

__all__ = [
    "Icd10CodeSystem",
    "condition_label",
    "condition_short_name",
    "icd10_display",
    "icd10_system",
    "medis_disease_keyno",
]


class Icd10CodeSystem(CodeSystem):
    """ICD-10 and ICD-10-CM: a code generalizes to its category, the code
    without its decimal part (``E11.9`` → ``E11``; spec §2.3, Issue #2470)."""

    def parents(self, code: str) -> tuple[str, ...]:
        category = code.split(".", 1)[0]
        return (category,) if category != code else ()


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
