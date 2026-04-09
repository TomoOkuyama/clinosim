#!/usr/bin/env python3
"""
Test script for Bedrock narrative generation.

Usage:
    python test_bedrock_narrative.py

Requirements:
    - boto3 installed: pip install boto3
    - AWS credentials configured (aws configure or environment variables)
    - IAM permission: bedrock:InvokeModel
"""

import sys
from pathlib import Path

# Add clinosim to path
sys.path.insert(0, str(Path(__file__).parent))

from clinosim.modules.llm_service.engine import (
    LLMService,
    LLMTaskType,
    PatientSummary,
    ClinicalEventData,
)
from clinosim.modules.llm_service.providers import BedrockProvider


def test_bedrock_provider():
    """Test BedrockProvider initialization and health check."""
    print("=" * 60)
    print("Test 1: BedrockProvider Health Check")
    print("=" * 60)

    try:
        provider = BedrockProvider({
            "region": "us-east-1",
            "model": "us.anthropic.claude-sonnet-4-6",  # Inference profile ID
        })

        if provider.health_check():
            print("✓ BedrockProvider initialized successfully")
        else:
            print("✗ BedrockProvider health check failed")
            return False

    except Exception as e:
        print(f"✗ Error initializing BedrockProvider: {e}")
        print("\nTroubleshooting:")
        print("  1. Check boto3 is installed: pip install boto3")
        print("  2. Check AWS credentials: aws sts get-caller-identity")
        print("  3. Check IAM permissions: bedrock:InvokeModel")
        return False

    return True


def test_narrative_generation():
    """Test narrative generation for all 5 required document types."""
    print("\n" + "=" * 60)
    print("Test 2: Narrative Generation (5 Document Types)")
    print("=" * 60)

    # Initialize provider with Sonnet 4.6 (using inference profile)
    provider = BedrockProvider({
        "region": "us-east-1",
        "model": "us.anthropic.claude-sonnet-4-6",  # Inference profile ID
    })

    # Initialize LLMService with Bedrock
    llm = LLMService(
        mode="llm",
        narrative_provider=provider,
        narrative_model_map={
            "medium": "us.anthropic.claude-sonnet-4-6",  # Inference profile ID
        },
    )

    # Sample patient
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

    # Test cases for 5 document types
    test_cases = [
        {
            "name": "1. Admission H&P (LOINC 34117-2)",
            "task_type": LLMTaskType.ADMISSION_HP,
            "event_data": {
                "symptoms": ["発熱", "咳嗽", "呼吸困難"],
                "symptom_days": 3,
            },
        },
        {
            "name": "2. Discharge Summary (LOINC 18842-5)",
            "task_type": LLMTaskType.DISCHARGE_SUMMARY,
            "event_data": {
                "final_diagnosis": "細菌性肺炎（Streptococcus pneumoniae）",
                "los_days": 14,
                "key_events": ["Day 3: 解熱", "Day 7: CRP正常化"],
                "discharge_medications": ["アモキシシリン", "アセトアミノフェン"],
            },
        },
        {
            "name": "3. Operative Note (LOINC 11504-8)",
            "task_type": LLMTaskType.OPERATIVE_NOTE,
            "event_data": {
                "procedure_type": "大腿骨頸部骨折 ORIF",
                "anesthesia_type": "全身麻酔",
                "duration_minutes": 120,
                "estimated_blood_loss_ml": 450,
                "preop_diagnosis": "大腿骨頸部骨折",
                "postop_diagnosis": "大腿骨頸部骨折（内固定術施行）",
                "findings": "骨折線明瞭、骨質良好",
                "intraop_complications": [],
            },
        },
        {
            "name": "4. Procedure Note (LOINC 28570-0)",
            "task_type": LLMTaskType.PROCEDURE_NOTE,
            "event_data": {
                "procedure_type": "中心静脈カテーテル挿入",
                "indication": "敗血症性ショック、輸液管理",
                "complications": [],
            },
        },
        {
            "name": "5. Death Note (LOINC 69730-0)",
            "task_type": LLMTaskType.DEATH_NOTE,
            "event_data": {
                "death_datetime": "2026-04-15 14:23",
                "cause_of_death": "敗血症性ショック、多臓器不全",
            },
        },
    ]

    results = []
    for test_case in test_cases:
        print(f"\n{test_case['name']}")
        print("-" * 60)

        event = ClinicalEventData(
            patient_summary=patient,
            event_data=test_case["event_data"],
            language="ja",
        )

        try:
            import traceback
            response = llm.generate(test_case["task_type"], event)

            if response.source == "llm" and response.text:
                print(f"✓ Generated ({len(response.text)} chars)")
                print(f"  Preview: {response.text[:150]}...")
                results.append(True)
            elif response.source == "template":
                print(f"⚠ Fell back to template")
                results.append(False)
            else:
                print(f"✗ No text generated")
                results.append(False)

        except Exception as e:
            import traceback
            print(f"✗ Error: {e}")
            print(f"  Traceback: {traceback.format_exc()}")
            results.append(False)

    # Summary
    print("\n" + "=" * 60)
    print("Summary")
    print("=" * 60)
    success_count = sum(results)
    total_count = len(results)
    print(f"Passed: {success_count}/{total_count}")

    # Cost report
    report = llm.cost_report()
    print(f"\nToken usage:")
    print(f"  Input:  {report['total_input_tokens']:,}")
    print(f"  Output: {report['total_output_tokens']:,}")
    print(f"  Calls:  {report['total_calls']}")
    print(f"  Fallbacks: {report['fallback_count']}")

    return success_count == total_count


def main():
    """Run all tests."""
    print("Testing Bedrock Narrative Generation")
    print("=" * 60)

    # Test 1: Provider initialization
    if not test_bedrock_provider():
        print("\n✗ Provider test failed. Exiting.")
        sys.exit(1)

    # Test 2: Narrative generation
    if not test_narrative_generation():
        print("\n✗ Some narrative tests failed.")
        sys.exit(1)

    print("\n" + "=" * 60)
    print("✓ All tests passed!")
    print("=" * 60)


if __name__ == "__main__":
    main()
