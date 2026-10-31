"""Declared namespaces of ``LifeEvent.disease_id`` and
``ConditionEvent.ground_truth_diseases`` values (Issue #2291).

Both fields carry one of four kinds of identifier. Consumers call
:func:`event_ref_kind` to tell them apart instead of guessing from the
string's shape:

- ``"disease"``   — an internal disease id with a disease protocol
  (``modules/disease/reference_data/<id>.yaml``)
- ``"encounter"`` — an ED / encounter condition id
  (``modules/encounter/reference_data/<id>.yaml``)
- ``"icd"``       — an ICD-10 / ICD-10-CM code registered in the code registry
  (pregnancy, delivery, newborn, cancer and chronic follow-up events)
- ``"label"``     — an event label from :data:`EVENT_LABELS`, the pediatric
  schedule, or ``unknown_<pattern>``
"""

from __future__ import annotations

import re
from functools import cache
from pathlib import Path
from typing import Literal

import yaml

from clinosim.codes import code_exists

EventRefKind = Literal["disease", "encounter", "icd", "label"]

# Population-calendar and perinatal event labels.
EVENT_LABELS: frozenset[str] = frozenset(
    {
        "annual_health_screening",
        "flu_vaccination",
        "colonoscopy_screening",
        "mammography_screening",
        "diabetic_retinopathy_screening",
        "newborn_birth",
    }
)

_ICD_SHAPE = re.compile(r"^[A-Z][0-9]{2}(\.[0-9A-Z]{1,4})?$")
_PEDIATRIC_SCHEDULE = (
    Path(__file__).resolve().parents[1] / "modules" / "pediatric" / "reference_data" / "pediatric_schedule.yaml"
)


@cache
def _pediatric_labels() -> frozenset[str]:
    raw = yaml.safe_load(_PEDIATRIC_SCHEDULE.read_text(encoding="utf-8")) or {}
    found: set[str] = set()

    def walk(node: object) -> None:
        if isinstance(node, dict):
            if isinstance(node.get("disease_id"), str):
                found.add(node["disease_id"])
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(raw)
    return frozenset(found)


@cache
def _disease_ids() -> frozenset[str]:
    from clinosim.modules.disease.protocol import load_all_disease_protocols

    return frozenset(load_all_disease_protocols())


@cache
def _encounter_ids() -> frozenset[str]:
    from clinosim.modules.encounter.protocol import load_all_encounter_conditions

    return frozenset(load_all_encounter_conditions())


def event_ref_kind(value: str) -> EventRefKind | None:
    """The namespace of a ``disease_id`` / ``ground_truth_diseases`` value, or
    ``None`` when it belongs to none of them (a producer bug)."""
    if value in _disease_ids():
        return "disease"
    if value in _encounter_ids():
        return "encounter"
    if value in EVENT_LABELS or value in _pediatric_labels() or value.startswith("unknown_"):
        return "label"
    if _ICD_SHAPE.match(value) and (code_exists("icd-10-cm", value) or code_exists("icd-10", value)):
        return "icd"
    return None
