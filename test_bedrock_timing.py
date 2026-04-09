#!/usr/bin/env python3
"""
Test script to measure Bedrock narrative generation timing.
Measures: input prep, inference, output processing.
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


def measure_single_generation():
    """Measure timing for a single narrative generation."""
    print("=" * 70)
    print("Bedrock Narrative Generation - Detailed Timing Analysis")
    print("=" * 70)

    # Initialize provider
    t0_provider = time.time()
    provider = BedrockProvider({
        "region": "us-east-1",
        "model": "us.anthropic.claude-sonnet-4-6",
    })
    t1_provider = time.time()
    print(f"\n[1] Provider initialization: {(t1_provider - t0_provider)*1000:.1f} ms")

    # Initialize service
    t0_service = time.time()
    llm = LLMService(
        mode="llm",
        narrative_provider=provider,
        narrative_model_map={"medium": "us.anthropic.claude-sonnet-4-6"},
    )
    t1_service = time.time()
    print(f"[2] LLMService initialization: {(t1_service - t0_service)*1000:.1f} ms")

    # Prepare patient data
    t0_prep = time.time()
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

    event = ClinicalEventData(
        patient_summary=patient,
        event_data={
            "final_diagnosis": "細菌性肺炎（Streptococcus pneumoniae）",
            "los_days": 14,
            "key_events": ["Day 3: 解熱", "Day 7: CRP正常化"],
            "discharge_medications": ["アモキシシリン", "アセトアミノフェン"],
        },
        language="ja",
    )
    t1_prep = time.time()
    print(f"[3] Input data preparation: {(t1_prep - t0_prep)*1000:.1f} ms")

    # Generate (with internal timing)
    print(f"\n[4] Discharge Summary generation:")
    t0_gen = time.time()
    response = llm.generate(LLMTaskType.DISCHARGE_SUMMARY, event)
    t1_gen = time.time()

    total_gen_time = (t1_gen - t0_gen) * 1000
    print(f"    Total generation time: {total_gen_time:.1f} ms ({total_gen_time/1000:.2f} sec)")

    # Output processing
    t0_output = time.time()
    text_length = len(response.text) if response.text else 0
    char_count = text_length
    t1_output = time.time()
    print(f"[5] Output processing: {(t1_output - t0_output)*1000:.1f} ms")

    # Results
    print(f"\n" + "=" * 70)
    print("Results:")
    print("=" * 70)
    print(f"✓ Generated: {char_count} characters")
    print(f"✓ Source: {response.source}")
    print(f"✓ Model: {response.model}")

    # Token report
    report = llm.cost_report()
    print(f"\nToken usage:")
    print(f"  Input tokens:  {report['total_input_tokens']}")
    print(f"  Output tokens: {report['total_output_tokens']}")

    # Timing breakdown
    print(f"\n" + "=" * 70)
    print("Timing Breakdown:")
    print("=" * 70)
    print(f"  Provider init:     {(t1_provider - t0_provider)*1000:7.1f} ms")
    print(f"  Service init:      {(t1_service - t0_service)*1000:7.1f} ms")
    print(f"  Input prep:        {(t1_prep - t0_prep)*1000:7.1f} ms")
    print(f"  Generation:        {total_gen_time:7.1f} ms ⬅ MAIN BOTTLENECK")
    print(f"  Output processing: {(t1_output - t0_output)*1000:7.1f} ms")
    print(f"  " + "-" * 66)
    total = (t1_output - t0_provider) * 1000
    print(f"  TOTAL:             {total:7.1f} ms ({total/1000:.2f} sec)")

    # Estimate inference time
    print(f"\n" + "=" * 70)
    print("Inference Time Estimate:")
    print("=" * 70)
    overhead = (t1_provider - t0_provider + t1_service - t0_service +
                t1_prep - t0_prep + t1_output - t0_output) * 1000
    inference_estimate = total_gen_time - overhead
    print(f"  Total generation:  {total_gen_time:7.1f} ms")
    print(f"  Local overhead:    {overhead:7.1f} ms")
    print(f"  Network+Inference: {inference_estimate:7.1f} ms (estimate)")
    print(f"                     ({inference_estimate/1000:.2f} sec)")


def measure_five_generations():
    """Measure timing for all 5 document types."""
    print("\n\n" + "=" * 70)
    print("5-Document Generation Timing")
    print("=" * 70)

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

    times = []
    t0_total = time.time()

    for name, task_type, event_data in test_cases:
        event = ClinicalEventData(
            patient_summary=patient,
            event_data=event_data,
            language="ja",
        )

        t0 = time.time()
        response = llm.generate(task_type, event)
        t1 = time.time()

        duration = (t1 - t0) * 1000
        times.append((name, duration))
        print(f"  {name:20s}: {duration:7.1f} ms ({duration/1000:.2f} sec)")

    t1_total = time.time()
    total_time = (t1_total - t0_total) * 1000

    print(f"  " + "-" * 66)
    print(f"  {'TOTAL (sequential)':20s}: {total_time:7.1f} ms ({total_time/1000:.2f} sec)")

    # Token report
    report = llm.cost_report()
    print(f"\n  Total input tokens:  {report['total_input_tokens']}")
    print(f"  Total output tokens: {report['total_output_tokens']}")
    print(f"  Total calls: {report['total_calls']}")

    # Parallel estimate
    max_time = max(t for _, t in times)
    print(f"\n  Estimated time if parallel: {max_time:.1f} ms ({max_time/1000:.2f} sec)")
    speedup = total_time / max_time
    print(f"  Potential speedup: {speedup:.1f}x")


if __name__ == "__main__":
    measure_single_generation()
    measure_five_generations()
