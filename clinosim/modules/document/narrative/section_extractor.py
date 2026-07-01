"""Per-section extraction for COMPOSITION documents (AD-65 E3).

Provides section_facts[<section_key>] for each COMPOSITION section
(hpi / assessment_plan / etc.). Enables section-level LLM replacement
(β-JP-1) without contaminating other sections.
"""

from __future__ import annotations

from clinosim.modules.document.narrative.fact_extractor import (
    extract_encounter_facts,
    extract_lab_facts,
    extract_medication_facts,
    extract_patient_facts,
)
from clinosim.modules.document.narrative.registry import DocumentTypeSpec
from clinosim.types.document import FactTag, NarrativeContext, SectionFacts


def extract_for_composition(
    ctx: NarrativeContext,
    spec: DocumentTypeSpec,
) -> dict[str, SectionFacts]:
    """Return {section_key: SectionFacts} for each spec.composition_sections."""
    if not getattr(spec, "composition_sections", None):
        return {}
    llm_enabled = set(getattr(spec, "llm_enabled_sections", ()) or ())
    hints = ctx.narrative_spine.disease_narrative_hints if ctx.narrative_spine else {}
    result: dict[str, SectionFacts] = {}
    for section_key in spec.composition_sections:
        facts = _facts_for_section(section_key, ctx)
        result[section_key] = SectionFacts(
            section_key=section_key,
            facts=facts,
            scenario_hint=hints.get(section_key, ""),
            llm_replaceable=section_key in llm_enabled,
        )
    return result


def _facts_for_section(section_key: str, ctx: NarrativeContext) -> list[FactTag]:
    if section_key in ("chief_complaint", "hpi", "history_of_present_illness"):
        return extract_encounter_facts(
            {
                "admission_diagnosis_code": getattr(ctx.encounter, "admission_diagnosis_code", ""),
            }
        )
    if section_key in ("past_medical_history", "chronic_conditions"):
        return extract_patient_facts(
            {
                "patient": {
                    "age": getattr(ctx.patient, "age", None),
                    "sex": getattr(ctx.patient, "sex", None),
                    "chronic_conditions": getattr(ctx.patient, "chronic_conditions", []),
                }
            }
        )
    if section_key in ("physical_examination", "vital_signs"):
        return []  # scenario_hint carries dominant guidance
    if section_key in ("labs", "laboratory_data", "assessment_and_plan"):
        return extract_lab_facts(ctx.lab_results)
    if section_key in ("medications", "medications_at_discharge"):
        return extract_medication_facts(ctx.medications)
    return []
