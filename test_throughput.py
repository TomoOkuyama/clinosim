#!/usr/bin/env python3
"""
Measure Bedrock throughput (tokens per second).
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from clinosim.modules.llm_service.engine import (
    LLMService,
    LLMTaskType,
    PatientSummary,
    ClinicalEventData,
)
from clinosim.modules.llm_service.providers import BedrockProvider


def measure_throughput():
    """Measure tokens/sec for each document type."""
    print("=" * 80)
    print("Bedrock Throughput Analysis (tokens/sec)")
    print("=" * 80)

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
        age=72, sex="M", country="JP",
        chief_complaint="呼吸困難と発熱",
        current_diagnosis="細菌性肺炎",
        relevant_conditions=["高血圧", "2型糖尿病"],
    )

    test_cases = [
        ("Admission H&P", LLMTaskType.ADMISSION_HP, {
            "symptoms": ["発熱", "咳嗽", "呼吸困難"],
            "symptom_days": 3,
        }),
        ("Discharge Summary", LLMTaskType.DISCHARGE_SUMMARY, {
            "final_diagnosis": "細菌性肺炎（Streptococcus pneumoniae）",
            "los_days": 14,
            "key_events": ["Day 3: 解熱", "Day 7: CRP正常化"],
            "discharge_medications": ["アモキシシリン", "アセトアミノフェン"],
        }),
        ("Operative Note", LLMTaskType.OPERATIVE_NOTE, {
            "procedure_type": "大腿骨頸部骨折 ORIF",
            "anesthesia_type": "全身麻酔",
            "duration_minutes": 120,
            "estimated_blood_loss_ml": 450,
            "preop_diagnosis": "大腿骨頸部骨折",
            "postop_diagnosis": "大腿骨頸部骨折（内固定術施行）",
            "findings": "骨折線明瞭、骨質良好",
            "intraop_complications": [],
        }),
        ("Procedure Note", LLMTaskType.PROCEDURE_NOTE, {
            "procedure_type": "中心静脈カテーテル挿入",
            "indication": "敗血症性ショック、輸液管理",
            "complications": [],
        }),
        ("Death Note", LLMTaskType.DEATH_NOTE, {
            "death_datetime": "2026-04-15 14:23",
            "cause_of_death": "敗血症性ショック、多臓器不全",
        }),
    ]

    print(f"\n{'Document Type':<20} {'Time (sec)':<12} {'Input':<8} {'Output':<8} {'Tokens/sec':<12}")
    print("-" * 80)

    results = []
    prev_input = 0
    prev_output = 0

    for name, task_type, event_data in test_cases:
        event = ClinicalEventData(
            patient_summary=patient,
            event_data=event_data,
            language="ja",
        )

        t0 = time.time()
        response = llm.generate(task_type, event)
        t1 = time.time()

        duration = t1 - t0

        # Get token counts for this call
        report = llm.cost_report()
        input_tokens = report['total_input_tokens'] - prev_input
        output_tokens = report['total_output_tokens'] - prev_output
        prev_input = report['total_input_tokens']
        prev_output = report['total_output_tokens']

        # Calculate throughput (output tokens / time)
        throughput = output_tokens / duration if duration > 0 else 0

        results.append({
            'name': name,
            'duration': duration,
            'input_tokens': input_tokens,
            'output_tokens': output_tokens,
            'throughput': throughput,
        })

        print(f"{name:<20} {duration:<12.2f} {input_tokens:<8} {output_tokens:<8} {throughput:<12.1f}")

    # Summary
    print("-" * 80)
    total_output = sum(r['output_tokens'] for r in results)
    total_time = sum(r['duration'] for r in results)
    avg_throughput = total_output / total_time if total_time > 0 else 0

    print(f"{'TOTAL':<20} {total_time:<12.2f} {'':<8} {total_output:<8} {avg_throughput:<12.1f}")

    print("\n" + "=" * 80)
    print("Analysis:")
    print("=" * 80)
    print(f"Average throughput: {avg_throughput:.1f} tokens/sec")

    # Benchmark comparison
    print(f"\nBenchmark comparison:")
    print(f"  Claude Sonnet 4.6 (API):     ~70-100 tokens/sec (typical)")
    print(f"  Claude Sonnet 4.6 (Bedrock): ~40-70 tokens/sec (typical)")
    print(f"  This measurement:            {avg_throughput:.1f} tokens/sec")

    if avg_throughput < 40:
        print(f"\n⚠️  WARNING: Throughput is LOWER than expected!")
        print(f"  Possible causes:")
        print(f"    - Network latency (check region)")
        print(f"    - Cold start (first request to Bedrock)")
        print(f"    - Throttling (check AWS quotas)")
        print(f"    - max_tokens setting too high")
    elif avg_throughput > 70:
        print(f"\n✓ Throughput is GOOD (within expected range)")
    else:
        print(f"\n✓ Throughput is ACCEPTABLE (normal for Bedrock)")

    # Check max_tokens settings
    print(f"\n" + "=" * 80)
    print("Current max_tokens settings:")
    print("=" * 80)
    max_tokens_map = {
        LLMTaskType.ADMISSION_HP: 3000,
        LLMTaskType.DISCHARGE_SUMMARY: 4000,
        LLMTaskType.OPERATIVE_NOTE: 2500,
        LLMTaskType.PROCEDURE_NOTE: 1500,
        LLMTaskType.DEATH_NOTE: 1000,
    }

    for r in results:
        task_name = r['name']
        actual = r['output_tokens']
        # Map name to task type
        if 'Admission' in task_name:
            max_tok = max_tokens_map[LLMTaskType.ADMISSION_HP]
        elif 'Discharge' in task_name:
            max_tok = max_tokens_map[LLMTaskType.DISCHARGE_SUMMARY]
        elif 'Operative' in task_name:
            max_tok = max_tokens_map[LLMTaskType.OPERATIVE_NOTE]
        elif 'Procedure' in task_name:
            max_tok = max_tokens_map[LLMTaskType.PROCEDURE_NOTE]
        else:
            max_tok = max_tokens_map[LLMTaskType.DEATH_NOTE]

        utilization = (actual / max_tok * 100) if max_tok > 0 else 0
        status = "✓" if utilization < 90 else "⚠️"
        print(f"  {status} {task_name:<20}: max={max_tok:4}, actual={actual:4} ({utilization:5.1f}%)")


if __name__ == "__main__":
    measure_throughput()
