"""Narrative generation module.

Generates clinical narrative documents from CIF structured data.
Supports 5 LOINC-compliant narrative types:
- Admission H&P (34117-2)
- Discharge Summary (18842-5)
- Operative Note (11504-8)
- Procedure Note (28570-0)
- Death Note (69730-0)
"""

from clinosim.modules.narrative.cif_extractor import (
    extract_admission_hp_data,
    extract_death_note_data,
    extract_discharge_summary_data,
    extract_operative_note_data,
    extract_procedure_note_data,
)
from clinosim.modules.narrative.engine import (
    generate_all_narratives,
    generate_narrative,
    identify_narratives_needed,
)
from clinosim.modules.narrative.prompt_builder import build_prompt

__all__ = [
    # CIF extraction
    "extract_admission_hp_data",
    "extract_discharge_summary_data",
    "extract_operative_note_data",
    "extract_procedure_note_data",
    "extract_death_note_data",
    # Engine functions
    "identify_narratives_needed",
    "generate_narrative",
    "generate_all_narratives",
    # Prompt building
    "build_prompt",
]
