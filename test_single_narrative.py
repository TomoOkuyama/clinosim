#!/usr/bin/env python3
"""
Generate a single narrative for clinical consistency checking.

Usage:
    python test_single_narrative.py                          # Default: admission_hp
    python test_single_narrative.py admission_hp             # Specify type
    python test_single_narrative.py discharge_summary
    python test_single_narrative.py operative_note
    python test_single_narrative.py procedure_note
    python test_single_narrative.py death_note

Output:
    1. Input data (what was sent to LLM)
    2. Generated narrative
    3. Consistency check points
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from clinosim.modules.llm_service.engine import (
    LLMService,
    LLMTaskType,
    PatientSummary,
    ClinicalEventData,
    _build_prompt,
)
from clinosim.modules.llm_service.providers import BedrockProvider


# Test data for each narrative type
TEST_DATA = {
    "admission_hp": {
        "patient": PatientSummary(
            age=72, sex="M", country="US",
            chief_complaint="Shortness of breath and fever",
            current_diagnosis="Bacterial pneumonia",
            relevant_conditions=["Hypertension", "Type 2 diabetes"],
        ),
        "event_data": {
            "symptoms": ["Fever", "Cough", "Dyspnea"],
            "symptom_days": 3,
        },
    },
    "discharge_summary": {
        "patient": PatientSummary(
            age=72, sex="M", country="US",
            chief_complaint="Shortness of breath and fever",
            current_diagnosis="Bacterial pneumonia",
        ),
        "event_data": {
            "final_diagnosis": "Bacterial pneumonia (Streptococcus pneumoniae)",
            "los_days": 14,
            "key_events": ["Day 3: Defervescence", "Day 7: CRP normalized"],
            "discharge_medications": ["Amoxicillin", "Acetaminophen"],
        },
    },
    "operative_note": {
        "patient": PatientSummary(
            age=72, sex="M", country="US",
            chief_complaint="Hip fracture",
            current_diagnosis="Femoral neck fracture",
        ),
        "event_data": {
            "procedure_type": "Femoral neck fracture ORIF",
            "anesthesia_type": "General anesthesia",
            "duration_minutes": 120,
            "estimated_blood_loss_ml": 450,
            "preop_diagnosis": "Femoral neck fracture",
            "postop_diagnosis": "Femoral neck fracture (internal fixation performed)",
            "findings": "Fracture line clear, good bone quality",
            "intraop_complications": [],
        },
    },
    "procedure_note": {
        "patient": PatientSummary(
            age=72, sex="M", country="US",
            chief_complaint="Septic shock",
            current_diagnosis="Septic shock",
        ),
        "event_data": {
            "procedure_type": "Central venous catheter insertion",
            "indication": "Septic shock, fluid management",
            "complications": [],
        },
    },
    "death_note": {
        "patient": PatientSummary(
            age=72, sex="M", country="US",
            chief_complaint="Septic shock",
            current_diagnosis="Septic shock",
        ),
        "event_data": {
            "death_datetime": "2026-04-15 14:23",
            "cause_of_death": "Septic shock, multiorgan failure",
        },
    },
}


def generate_single_narrative(narrative_type: str):
    """Generate a single narrative and display consistency check info."""

    # Map string to enum
    task_type_map = {
        "admission_hp": LLMTaskType.ADMISSION_HP,
        "discharge_summary": LLMTaskType.DISCHARGE_SUMMARY,
        "operative_note": LLMTaskType.OPERATIVE_NOTE,
        "procedure_note": LLMTaskType.PROCEDURE_NOTE,
        "death_note": LLMTaskType.DEATH_NOTE,
    }

    if narrative_type not in task_type_map:
        print(f"Error: Unknown narrative type '{narrative_type}'")
        print(f"Available types: {', '.join(task_type_map.keys())}")
        sys.exit(1)

    task_type = task_type_map[narrative_type]
    test_data = TEST_DATA[narrative_type]

    print("=" * 80)
    print(f"SINGLE NARRATIVE GENERATION: {narrative_type.upper()}")
    print("=" * 80)

    # Initialize provider
    print("\n[1] Initializing Bedrock provider...")
    provider = BedrockProvider({
        "region": "us-east-1",
        "model": "us.anthropic.claude-sonnet-4-6",
    })

    llm = LLMService(
        mode="llm",
        narrative_provider=provider,
        narrative_model_map={"medium": "us.anthropic.claude-sonnet-4-6"},
    )
    print("    ✓ Provider ready")

    # Prepare event
    event = ClinicalEventData(
        patient_summary=test_data["patient"],
        event_data=test_data["event_data"],
        language="en",
    )

    # Show input data
    print("\n" + "=" * 80)
    print("[2] INPUT DATA (What is being sent to LLM)")
    print("=" * 80)

    system_prompt, user_prompt = _build_prompt(task_type, event, "en")

    print("\n--- SYSTEM PROMPT ---")
    print(system_prompt)

    print("\n--- USER PROMPT (Structured Data) ---")
    print(user_prompt)

    print("\n--- METADATA ---")
    print(f"Patient age: {test_data['patient'].age}")
    print(f"Patient sex: {test_data['patient'].sex}")
    print(f"Chief complaint: {test_data['patient'].chief_complaint}")
    print(f"Current diagnosis: {test_data['patient'].current_diagnosis}")

    # Generate narrative
    print("\n" + "=" * 80)
    print("[3] GENERATING NARRATIVE...")
    print("=" * 80)

    import time
    t0 = time.time()
    response = llm.generate(task_type, event)
    t1 = time.time()

    print(f"✓ Generated in {t1-t0:.1f} seconds")
    print(f"  Source: {response.source}")
    print(f"  Model: {response.model}")

    # Token usage
    report = llm.cost_report()
    print(f"  Input tokens: {report['total_input_tokens']}")
    print(f"  Output tokens: {report['total_output_tokens']}")

    # Show generated narrative
    print("\n" + "=" * 80)
    print("[4] GENERATED NARRATIVE")
    print("=" * 80)
    print()
    print(response.text)
    print()

    # Consistency check points
    print("=" * 80)
    print("[5] CONSISTENCY CHECK POINTS")
    print("=" * 80)

    print("\n⚠️  CURRENT LIMITATIONS:")
    print("  - Input data contains ONLY minimal information (age, sex, diagnosis)")
    print("  - NO real vitals from CIF (e.g., no actual BP, HR, temp, SpO2)")
    print("  - NO real lab results from CIF (e.g., no actual WBC, CRP values)")
    print("  - NO disease protocol context (typical course, standard treatment)")
    print("  - NO encounter scenario context (severity, standard workup)")
    print()
    print("➡️  As a result, LLM HALLUCINATES clinical data:")

    # Check for hallucinated data patterns
    narrative_lower = response.text.lower()
    hallucinated = []

    # Vital signs
    if any(x in narrative_lower for x in ["bp:", "hr:", "temp:", "spo2", "blood pressure", "heart rate"]):
        hallucinated.append("  ✗ Vital signs (BP, HR, temp, SpO2) - NOT from CIF")

    # Lab results
    if any(x in narrative_lower for x in ["wbc", "crp", "glucose", "creatinine", "albumin"]):
        hallucinated.append("  ✗ Lab results (WBC, CRP, etc.) - NOT from CIF")

    # Imaging
    if any(x in narrative_lower for x in ["x-ray", "xray", "ct", "mri", "ultrasound", "infiltrate"]):
        hallucinated.append("  ✗ Imaging findings - NOT from CIF")

    # Physical exam
    if any(x in narrative_lower for x in ["breath sounds", "lung", "cardiac", "abdomen", "exam"]):
        hallucinated.append("  ✗ Physical exam findings - NOT from CIF")

    if hallucinated:
        print("\n".join(hallucinated))
    else:
        print("  (No obvious hallucinated data detected)")

    print("\n✓ DATA ACTUALLY FROM INPUT:")
    print(f"  ✓ Patient age: {test_data['patient'].age}")
    print(f"  ✓ Patient sex: {test_data['patient'].sex}")
    print(f"  ✓ Chief complaint: {test_data['patient'].chief_complaint}")
    print(f"  ✓ Diagnosis: {test_data['patient'].current_diagnosis}")

    if narrative_type == "discharge_summary":
        print(f"  ✓ Key events: {test_data['event_data']['key_events']}")
        print(f"  ✓ Discharge meds: {test_data['event_data']['discharge_medications']}")
    elif narrative_type == "operative_note":
        print(f"  ✓ Procedure: {test_data['event_data']['procedure_type']}")
        print(f"  ✓ EBL: {test_data['event_data']['estimated_blood_loss_ml']} mL")

    print("\n" + "=" * 80)
    print("[6] NEXT STEPS TO FIX HALLUCINATION")
    print("=" * 80)
    print()
    print("To generate clinically consistent narratives:")
    print()
    print("1. Implement cif_extractor.py module:")
    print("   - Extract REAL vitals from CIF.vital_signs")
    print("   - Extract REAL labs from CIF.lab_results")
    print("   - Extract REAL procedures from CIF.procedures")
    print()
    print("2. Load disease protocol YAML:")
    print("   - bacterial_pneumonia.yaml (course_archetypes, discharge_criteria)")
    print("   - Use to add clinical context to prompt")
    print()
    print("3. Update _build_prompt() to include CIF data:")
    print("   - Current: Only age, sex, diagnosis")
    print("   - Needed: Vitals, labs, meds, timeline")
    print()
    print("4. Validate narrative against CIF:")
    print("   - Check all vitals/labs in narrative exist in CIF")
    print("   - Check all outcomes have AFTER data in CIF")
    print()
    print("See: NARRATIVE_CIF_MAPPING.md for complete requirements")
    print()


def main():
    narrative_type = sys.argv[1] if len(sys.argv) > 1 else "admission_hp"
    generate_single_narrative(narrative_type)


if __name__ == "__main__":
    main()
