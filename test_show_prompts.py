#!/usr/bin/env python3
"""
Show actual prompts sent to Bedrock for each document type.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from clinosim.modules.llm_service.engine import (
    LLMTaskType,
    PatientSummary,
    ClinicalEventData,
    _build_prompt,
)


def show_all_prompts():
    """Display prompts for all 5 document types."""

    patient = PatientSummary(
        age=72,
        sex="M",
        country="JP",
        chief_complaint="呼吸困難と発熱",
        current_diagnosis="細菌性肺炎",
        diagnosis_confidence=0.85,
        hospital_day=5,
        department="internal_medicine",
        relevant_conditions=["高血圧", "2型糖尿病"],
    )

    test_cases = [
        ("Admission H&P (LOINC 34117-2)", LLMTaskType.ADMISSION_HP, {
            "symptoms": ["発熱", "咳嗽", "呼吸困難"],
            "symptom_days": 3,
        }),
        ("Discharge Summary (LOINC 18842-5)", LLMTaskType.DISCHARGE_SUMMARY, {
            "final_diagnosis": "細菌性肺炎（Streptococcus pneumoniae）",
            "los_days": 14,
            "key_events": ["Day 3: 解熱", "Day 7: CRP正常化"],
            "discharge_medications": ["アモキシシリン", "アセトアミノフェン"],
        }),
        ("Operative Note (LOINC 11504-8)", LLMTaskType.OPERATIVE_NOTE, {
            "procedure_type": "大腿骨頸部骨折 ORIF",
            "anesthesia_type": "全身麻酔",
            "duration_minutes": 120,
            "estimated_blood_loss_ml": 450,
            "preop_diagnosis": "大腿骨頸部骨折",
            "postop_diagnosis": "大腿骨頸部骨折（内固定術施行）",
            "findings": "骨折線明瞭、骨質良好",
            "intraop_complications": [],
        }),
        ("Procedure Note (LOINC 28570-0)", LLMTaskType.PROCEDURE_NOTE, {
            "procedure_type": "中心静脈カテーテル挿入",
            "indication": "敗血症性ショック、輸液管理",
            "complications": [],
        }),
        ("Death Note (LOINC 69730-0)", LLMTaskType.DEATH_NOTE, {
            "death_datetime": "2026-04-15 14:23",
            "cause_of_death": "敗血症性ショック、多臓器不全",
        }),
    ]

    for i, (name, task_type, event_data) in enumerate(test_cases, 1):
        event = ClinicalEventData(
            patient_summary=patient,
            event_data=event_data,
            language="ja",
        )

        system_prompt, user_prompt = _build_prompt(task_type, event, "ja")

        print("=" * 80)
        print(f"{i}. {name}")
        print("=" * 80)

        print("\n[SYSTEM PROMPT]")
        print("-" * 80)
        print(system_prompt)

        print("\n[USER PROMPT]")
        print("-" * 80)
        print(user_prompt)

        # Calculate approximate token count (rough estimate: 1 token ≈ 4 chars for English, 1.5 chars for Japanese)
        total_chars = len(system_prompt) + len(user_prompt)
        estimated_tokens = total_chars / 2  # rough average

        print("\n[METRICS]")
        print("-" * 80)
        print(f"System prompt: {len(system_prompt)} chars")
        print(f"User prompt:   {len(user_prompt)} chars")
        print(f"Total:         {total_chars} chars")
        print(f"Est. tokens:   ~{int(estimated_tokens)}")
        print()


if __name__ == "__main__":
    show_all_prompts()
