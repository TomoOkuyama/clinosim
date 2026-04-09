#!/usr/bin/env python3
"""
Display actual generated narratives with concise prompts.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from clinosim.modules.llm_service.engine import (
    LLMService,
    LLMTaskType,
    PatientSummary,
    ClinicalEventData,
)
from clinosim.modules.llm_service.providers import BedrockProvider


def show_all_narratives():
    """Generate and display all 5 narrative types."""

    provider = BedrockProvider({
        "region": "us-east-1",
        "model": "us.anthropic.claude-sonnet-4-6",
    })

    llm = LLMService(
        mode="llm",
        narrative_provider=provider,
        narrative_model_map={"medium": "us.anthropic.claude-sonnet-4-6"},
    )

    patient = PatientSummary(
        age=72, sex="M", country="US",
        chief_complaint="Shortness of breath and fever",
        current_diagnosis="Bacterial pneumonia",
        relevant_conditions=["Hypertension", "Type 2 diabetes"],
    )

    test_cases = [
        ("Admission H&P (LOINC 34117-2)", LLMTaskType.ADMISSION_HP, {
            "symptoms": ["Fever", "Cough", "Dyspnea"],
            "symptom_days": 3,
        }),
        ("Discharge Summary (LOINC 18842-5)", LLMTaskType.DISCHARGE_SUMMARY, {
            "final_diagnosis": "Bacterial pneumonia (Streptococcus pneumoniae)",
            "los_days": 14,
            "key_events": ["Day 3: Defervescence", "Day 7: CRP normalized"],
            "discharge_medications": ["Amoxicillin", "Acetaminophen"],
        }),
        ("Operative Note (LOINC 11504-8)", LLMTaskType.OPERATIVE_NOTE, {
            "procedure_type": "Femoral neck fracture ORIF",
            "anesthesia_type": "General anesthesia",
            "duration_minutes": 120,
            "estimated_blood_loss_ml": 450,
            "preop_diagnosis": "Femoral neck fracture",
            "postop_diagnosis": "Femoral neck fracture (internal fixation performed)",
            "findings": "Fracture line clear, good bone quality",
            "intraop_complications": [],
        }),
        ("Procedure Note (LOINC 28570-0)", LLMTaskType.PROCEDURE_NOTE, {
            "procedure_type": "Central venous catheter insertion",
            "indication": "Septic shock, fluid management",
            "complications": [],
        }),
        ("Death Note (LOINC 69730-0)", LLMTaskType.DEATH_NOTE, {
            "death_datetime": "2026-04-15 14:23",
            "cause_of_death": "Septic shock, multiorgan failure",
        }),
    ]

    for i, (name, task_type, event_data) in enumerate(test_cases, 1):
        print("=" * 80)
        print(f"{i}. {name}")
        print("=" * 80)

        event = ClinicalEventData(
            patient_summary=patient,
            event_data=event_data,
            language="en",
        )

        response = llm.generate(task_type, event)

        print(f"\n文字数: {len(response.text)} 文字")
        print(f"ソース: {response.source}")
        print(f"モデル: {response.model}")
        print("\n" + "-" * 80)
        print("内容:")
        print("-" * 80)
        print(response.text)
        print("\n")

    # Token report
    report = llm.cost_report()
    print("=" * 80)
    print("トークン使用量サマリー")
    print("=" * 80)
    print(f"入力トークン:  {report['total_input_tokens']:,}")
    print(f"出力トークン:  {report['total_output_tokens']:,}")
    print(f"API呼び出し:   {report['total_calls']}")
    print(f"フォールバック: {report['fallback_count']}")


if __name__ == "__main__":
    show_all_narratives()
