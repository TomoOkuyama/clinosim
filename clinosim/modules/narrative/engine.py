"""Narrative generation engine.

Orchestrates the complete narrative generation flow:
1. Identify which narratives are needed for each patient
2. Extract relevant CIF data for each narrative type
3. Generate narrative with LLM
4. Store narrative in CIF
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from clinosim.modules.narrative.cif_extractor import (
    extract_admission_hp_data,
    extract_death_note_data,
    extract_discharge_summary_data,
    extract_operative_note_data,
    extract_procedure_note_data,
)
from clinosim.types.encounter import EncounterType
from clinosim.types.narrative import NARRATIVE_LOINC_CODES, NarrativeDocument

if TYPE_CHECKING:
    from clinosim.types.output import CIFDataset, CIFPatientRecord


def identify_narratives_needed(cif_record: CIFPatientRecord) -> list[str]:
    """Identify which narrative types are needed for this patient.

    Args:
        cif_record: Complete patient record with encounters, procedures, etc.

    Returns:
        List of narrative type strings, e.g., ["admission_hp", "discharge_summary"]

    Logic:
        - INPATIENT encounter → Admission H&P
        - INPATIENT with discharge_datetime → Discharge Summary
        - INPATIENT with discharge_disposition="exp" → Death Note (instead of Discharge)
        - Surgical procedure → Operative Note
        - Bedside procedure → Procedure Note
    """
    needed = []

    # Check encounters
    for encounter in cif_record.encounters:
        if encounter.encounter_type == EncounterType.INPATIENT:
            # All inpatient encounters need Admission H&P
            needed.append("admission_hp")

            # Discharged patients need Discharge Summary or Death Note
            if encounter.discharge_datetime:
                if cif_record.deceased and encounter.discharge_disposition == "exp":
                    # Death discharge → Death Note
                    needed.append("death_note")
                else:
                    # Normal discharge → Discharge Summary
                    needed.append("discharge_summary")

        # ED and outpatient encounters don't get narratives in v0.1
        # Future: ED note (LOINC 34111-5), Office visit note (LOINC 11506-3)

    # Check procedures
    if cif_record.procedures:
        for procedure in cif_record.procedures:
            # TODO: Implement is_surgical_procedure() and is_bedside_procedure()
            # based on procedure code/type
            # For now, assume first procedure is surgical if patient has procedures
            if "surgical" in getattr(procedure, "procedure_type", "").lower():
                needed.append("operative_note")
            elif "procedure" in getattr(procedure, "procedure_type", "").lower():
                needed.append("procedure_note")

    # Remove duplicates (patient may have multiple encounters/procedures)
    return list(set(needed))


def generate_all_narratives(
    cif_dataset: CIFDataset,
    llm_config: dict,
    language: str = "en",
) -> None:
    """Generate narratives for all patients in dataset.

    Modifies cif_dataset in place by adding NarrativeDocument objects
    to each patient's narratives list.

    Args:
        cif_dataset: Complete dataset with all patient records
        llm_config: LLM configuration dict (provider, model, etc.)
        language: Language code ("en" or "ja")

    Process:
        For each patient:
        1. Identify needed narratives
        2. Extract CIF data for each narrative type
        3. Generate narrative with LLM
        4. Add NarrativeDocument to patient's narratives list

    Updates:
        - cif_dataset.patients[].narratives (adds NarrativeDocument objects)
        - cif_dataset.metadata.narrative_stats (token counts, cost)
    """
    from clinosim.modules.llm_service.providers import create_llm_provider

    # Initialize LLM provider
    provider = create_llm_provider(llm_config)

    # Extraction functions map
    extractors = {
        "admission_hp": extract_admission_hp_data,
        "discharge_summary": extract_discharge_summary_data,
        "operative_note": extract_operative_note_data,
        "procedure_note": extract_procedure_note_data,
        "death_note": extract_death_note_data,
    }

    # Track statistics
    total_narratives = 0
    total_input_tokens = 0
    total_output_tokens = 0

    # Process each patient
    for cif_record in cif_dataset.patients:
        # Step 1: Identify needed narratives
        needed = identify_narratives_needed(cif_record)

        for narrative_type in needed:
            # Step 2: Extract relevant data
            extractor = extractors[narrative_type]
            extracted_data = extractor(cif_record)

            if extracted_data is None:
                # Insufficient data to generate this narrative
                continue

            # Step 3: Generate narrative with LLM
            try:
                narrative = generate_narrative(
                    narrative_type=narrative_type,
                    extracted_data=extracted_data,
                    language=language,
                    provider=provider,
                    llm_config=llm_config,
                )

                # Step 4: Store in CIF
                cif_record.narratives.append(narrative)

                # Update statistics
                total_narratives += 1
                total_input_tokens += narrative.input_tokens
                total_output_tokens += narrative.output_tokens

            except Exception as e:
                # Log error and continue with next narrative
                print(f"Error generating {narrative_type} for patient {cif_record.patient.patient_id}: {e}")
                continue

    # Update dataset metadata with statistics
    if not hasattr(cif_dataset.metadata, "narrative_stats"):
        cif_dataset.metadata.narrative_stats = {}  # type: ignore

    cif_dataset.metadata.narrative_stats = {  # type: ignore
        "total_narratives_generated": total_narratives,
        "total_input_tokens": total_input_tokens,
        "total_output_tokens": total_output_tokens,
        # TODO: Calculate estimated cost based on provider pricing
        "estimated_cost_usd": 0.0,
    }


def generate_narrative(
    narrative_type: str,
    extracted_data: dict,
    language: str,
    provider,
    llm_config: dict,
) -> NarrativeDocument:
    """Generate a single narrative document.

    Args:
        narrative_type: Type of narrative ("admission_hp", "discharge_summary", etc.)
        extracted_data: Dict of CIF data extracted for this narrative
        language: Language code ("en" or "ja")
        provider: LLM provider instance
        llm_config: LLM configuration dict

    Returns:
        NarrativeDocument with generated text and metadata

    Raises:
        Exception: If LLM generation fails
    """
    from clinosim.modules.narrative.prompt_builder import build_prompt

    # Build prompt from extracted data
    system_prompt, user_prompt = build_prompt(
        narrative_type=narrative_type,
        extracted_data=extracted_data,
        language=language,
    )

    # Get max_tokens for this narrative type
    max_tokens_map = {
        "admission_hp": 3000,
        "discharge_summary": 4000,
        "operative_note": 2500,
        "procedure_note": 1500,
        "death_note": 1000,
    }
    max_tokens = max_tokens_map.get(narrative_type, 2000)

    # Call LLM
    response = provider.complete(
        prompt=user_prompt,
        model=llm_config.get("model", "us.anthropic.claude-sonnet-4-6"),
        max_tokens=max_tokens,
        system_prompt=system_prompt,
    )

    # Create NarrativeDocument
    encounter_id = extracted_data.get("encounter", {}).encounter_id if "encounter" in extracted_data else ""

    narrative = NarrativeDocument(
        narrative_id=f"narr-{encounter_id}-{narrative_type}",
        narrative_type=narrative_type,
        loinc_code=NARRATIVE_LOINC_CODES[narrative_type],
        text=response.text,
        language=language,
        encounter_id=encounter_id,
        model=llm_config.get("model", "unknown"),
        source="llm",
        input_tokens=response.input_tokens,
        output_tokens=response.output_tokens,
    )

    return narrative
