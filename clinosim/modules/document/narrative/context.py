"""NarrativeContext factory (CIF → ctx)."""

from __future__ import annotations

from typing import Any

from clinosim.modules._shared import get_attr_or_key as _o
from clinosim.modules._shared import resolve_lang
from clinosim.types.document import DocumentType, NarrativeContext


def build_narrative_context(
    record: Any,
    encounter: Any,
    document_type: DocumentType,
    day_index: int,
    country: str,
    disease_protocol: Any | None = None,
    encounter_protocol: Any | None = None,
    clinical_course_archetype: str = "uncomplicated_improvement",
    severity: str = "moderate",
    los_days: int = 1,
) -> NarrativeContext:
    """CIF record + encounter → NarrativeContext.

    Generator (template / LLM) は本 ctx のみ参照。day_index で daily generation
    の段階を渡す (progress note は 0..LOS、H&P = 0、Discharge = LOS-1)。
    """
    lang = resolve_lang(country)
    locale = country.lower()
    patient = _o(record, "patient", None)
    allergies: list[Any] = _o(patient, "allergies", []) if patient is not None else []
    return NarrativeContext(
        patient=patient,
        encounter=encounter,
        encounter_type=_o(encounter, "encounter_type", None),
        disease_protocol=disease_protocol,
        encounter_protocol=encounter_protocol,
        clinical_course_archetype=clinical_course_archetype,
        severity=severity,
        day_index=day_index,
        los_days=los_days,
        vitals=_o(record, "vital_signs", []) or [],
        lab_results=_o(record, "lab_results", []) or [],
        medications=_o(record, "medication_administrations", []) or [],
        diagnoses=_o(record, "diagnoses", []) or [],
        procedures=_o(record, "procedures", []) or [],
        allergies=allergies or [],
        document_type=document_type,
        target_lang=lang,
        locale=locale,
    )
