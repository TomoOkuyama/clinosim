"""Deterministic fact-first extraction (AD-65 E2).

Materializes a list of FactTag entries from structural CIF. Generators
use this list to constrain narrative output — β-JP-1 LLMNarrativePass
will refuse to emit numbers not present in materialized_facts.
"""

from __future__ import annotations

from typing import Any

from clinosim.modules._shared import get_attr_or_key
from clinosim.types.document import FactTag


def extract_patient_facts(patient_dict: dict[str, Any]) -> list[FactTag]:
    profile = patient_dict.get("patient", {}) or {}
    facts: list[FactTag] = []
    if age := profile.get("age"):
        facts.append(FactTag(key="patient.age", value=str(age), source="profile.demographics"))
    if sex := profile.get("sex"):
        facts.append(FactTag(key="patient.sex", value=str(sex), source="profile.demographics"))
    for cc in profile.get("chronic_conditions", []) or []:
        code = cc.get("code") if isinstance(cc, dict) else str(cc)
        if code:
            facts.append(
                FactTag(key=f"chronic.{code}", value="present", source="profile.chronic_conditions")
            )
    return facts


def extract_encounter_facts(encounter_dict: dict[str, Any]) -> list[FactTag]:
    facts: list[FactTag] = []
    if dx := encounter_dict.get("admission_diagnosis_code"):
        facts.append(
            FactTag(key="diagnosis.admission_icd", value=str(dx), source="structural.encounter")
        )
    if dx := encounter_dict.get("discharge_diagnosis_code"):
        facts.append(
            FactTag(key="diagnosis.discharge_icd", value=str(dx), source="structural.encounter")
        )
    return facts


def extract_lab_facts(lab_results: list[Any]) -> list[FactTag]:
    """F-9 adv-1: use get_attr_or_key for dict/dataclass dual access.

    Prior `getattr(lab, "value", None) or (lab.get("value") if isinstance(lab,
    dict) else None)` short-circuited on falsy values: a dataclass fixture
    with ``value=0.0`` produced ``0.0 or None → None`` and the fact was
    silently dropped. Dict-from-JSON path worked correctly (0.0 stays 0.0).
    Silent divergence between test fixtures and production is exactly the
    β-JP-1 LLM hallucination surface AD-65 is trying to prevent.
    """
    facts: list[FactTag] = []
    for lab in lab_results or []:
        name = get_attr_or_key(lab, "test_name", None)
        value = get_attr_or_key(lab, "value", None)
        day = get_attr_or_key(lab, "day_index", None)
        if name and value is not None:
            facts.append(
                FactTag(
                    key=f"lab.{name.lower()}.day{day if day is not None else 'x'}",
                    value=str(value),
                    source="structural.observations",
                )
            )
    return facts


def extract_medication_facts(medications: list[Any]) -> list[FactTag]:
    facts: list[FactTag] = []
    for m in medications or []:
        name = get_attr_or_key(m, "drug_name", None)
        dose = get_attr_or_key(m, "dose", None)
        if name:
            facts.append(
                FactTag(
                    key=f"med.{name.lower().replace(' ', '_')}",
                    value=str(dose) if dose else "administered",
                    source="structural.medications",
                )
            )
    return facts


def extract_all_facts(patient_dict: Any, encounter_dict: Any, ctx: Any) -> list[FactTag]:
    """Combined extractor from all sources — used by NarrativePass._build_context."""
    facts: list[FactTag] = []
    facts.extend(extract_patient_facts(patient_dict))
    facts.extend(extract_encounter_facts(encounter_dict))
    facts.extend(extract_lab_facts(getattr(ctx, "lab_results", [])))
    facts.extend(extract_medication_facts(getattr(ctx, "medications", [])))
    return facts
