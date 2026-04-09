"""Narrative document types for CIF."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class NarrativeDocument:
    """A single narrative document (e.g., Admission H&P, Discharge Summary).

    Stored in CIFPatientRecord.narratives list.
    Exported as FHIR DocumentReference in output.
    """

    # Identification
    narrative_id: str = ""  # Unique ID: e.g., "narr-ENC123-admission-hp"
    narrative_type: str = ""  # "admission_hp", "discharge_summary", etc.
    loinc_code: str = ""  # "34117-2", "18842-5", "11504-8", "28570-0", "69730-0"

    # Content
    text: str = ""  # Generated narrative text
    language: str = "en"  # "en" or "ja"

    # Metadata
    encounter_id: str = ""  # Related encounter
    generated_datetime: datetime = field(default_factory=datetime.now)
    model: str = ""  # e.g., "us.anthropic.claude-sonnet-4-6"
    source: str = "llm"  # "llm" or "template"

    # Token usage (for cost tracking)
    input_tokens: int = 0
    output_tokens: int = 0


# LOINC codes for the 5 required narrative types
NARRATIVE_LOINC_CODES = {
    "admission_hp": "34117-2",  # History and physical note
    "discharge_summary": "18842-5",  # Discharge summary
    "operative_note": "11504-8",  # Surgical operation note
    "procedure_note": "28570-0",  # Procedure note
    "death_note": "69730-0",  # Death summary note
}


NARRATIVE_DISPLAY_NAMES = {
    "admission_hp": "History and physical note",
    "discharge_summary": "Discharge summary",
    "operative_note": "Surgical operation note",
    "procedure_note": "Procedure note",
    "death_note": "Death summary note",
}
