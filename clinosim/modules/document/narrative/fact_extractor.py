"""Deterministic fact-first extraction (AD-65 E2).

Materializes a list of FactTag entries from structural CIF. Generators
use this list to constrain narrative output — β-JP-1 LLMNarrativePass
will refuse to emit numbers not present in materialized_facts.
"""

from __future__ import annotations

from typing import Any

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
    facts: list[FactTag] = []
    for lab in lab_results or []:
        name = getattr(lab, "test_name", None) or (
            lab.get("test_name") if isinstance(lab, dict) else None
        )
        value = getattr(lab, "value", None) or (lab.get("value") if isinstance(lab, dict) else None)
        day = getattr(lab, "day_index", None) or (
            lab.get("day_index") if isinstance(lab, dict) else None
        )
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
        name = getattr(m, "drug_name", None) or (
            m.get("drug_name") if isinstance(m, dict) else None
        )
        dose = getattr(m, "dose", None) or (m.get("dose") if isinstance(m, dict) else None)
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
