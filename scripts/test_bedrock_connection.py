#!/usr/bin/env python3
"""Pre-flight check for Bedrock connectivity.

Run this first on any new environment to verify:
  1. boto3 is installed
  2. AWS credentials are valid
  3. Bedrock Converse API responds
  4. clinosim BedrockProvider produces text

Usage:
    python scripts/test_bedrock_connection.py
    python scripts/test_bedrock_connection.py --region us-east-1
    python scripts/test_bedrock_connection.py --model us.anthropic.claude-sonnet-4-20250514-v1:0

Exit codes:
    0 = all checks passed
    1 = one or more checks failed (see output)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Ensure clinosim is importable when run from repo root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main() -> int:
    parser = argparse.ArgumentParser(description="Test Bedrock connectivity")
    parser.add_argument("--region", default="us-east-1", help="AWS region")
    parser.add_argument("--profile", default=None, help="AWS profile name")
    parser.add_argument(
        "--model",
        default="us.anthropic.claude-sonnet-4-20250514-v1:0",
        help="Bedrock model ID to test",
    )
    args = parser.parse_args()

    ok = True

    # ---- Check 1: boto3 ----
    print("=" * 60)
    print("Check 1: boto3 installation")
    print("=" * 60)
    try:
        import boto3
        print(f"  OK: boto3 {boto3.__version__}")
    except ImportError:
        print("  FAIL: boto3 not installed")
        print("  Fix: pip install boto3")
        return 1

    # ---- Check 2: AWS credentials ----
    print("\n" + "=" * 60)
    print("Check 2: AWS credentials")
    print("=" * 60)
    try:
        session = boto3.Session(
            region_name=args.region,
            profile_name=args.profile,
        )
        sts = session.client("sts")
        identity = sts.get_caller_identity()
        print(f"  OK: Account={identity['Account']}")
        print(f"      ARN={identity['Arn']}")
    except Exception as e:
        print(f"  FAIL: {type(e).__name__}: {e}")
        print("  Fix: aws configure, set env vars, or attach IAM role")
        return 1

    # ---- Check 3: Bedrock runtime client ----
    print("\n" + "=" * 60)
    print("Check 3: Bedrock runtime client")
    print("=" * 60)
    try:
        client = session.client("bedrock-runtime")
        print(f"  OK: bedrock-runtime client created in {args.region}")
    except Exception as e:
        print(f"  FAIL: {type(e).__name__}: {e}")
        ok = False

    # ---- Check 4: Converse API call ----
    print("\n" + "=" * 60)
    print(f"Check 4: Converse API ({args.model})")
    print("=" * 60)
    try:
        import time
        t0 = time.time()
        resp = client.converse(
            modelId=args.model,
            messages=[
                {
                    "role": "user",
                    "content": [{"text": "Say 'Hello from Bedrock' in exactly 4 words."}],
                }
            ],
            system=[{"text": "You are a test assistant. Reply concisely."}],
            inferenceConfig={"maxTokens": 50, "temperature": 0.0},
        )
        latency_ms = int((time.time() - t0) * 1000)

        output = resp.get("output", {}).get("message", {})
        content = output.get("content", [])
        text = "".join(b.get("text", "") for b in content if "text" in b)
        usage = resp.get("usage", {})

        print(f"  OK: response in {latency_ms}ms")
        print(f"      text: {text!r}")
        print(f"      tokens: in={usage.get('inputTokens', 0)} out={usage.get('outputTokens', 0)}")
        print(f"      stop_reason: {resp.get('stopReason', '')}")
    except client.exceptions.AccessDeniedException as e:
        print(f"  FAIL: AccessDenied — model {args.model} not enabled in {args.region}")
        print(f"        Go to Bedrock console → Model access → Request access")
        print(f"        Error: {e}")
        ok = False
    except Exception as e:
        print(f"  FAIL: {type(e).__name__}: {e}")
        ok = False

    # ---- Check 5: clinosim BedrockProvider ----
    print("\n" + "=" * 60)
    print("Check 5: clinosim BedrockProvider")
    print("=" * 60)
    try:
        from clinosim.modules.llm_service.providers.bedrock import BedrockProvider

        provider = BedrockProvider({
            "region": args.region,
            "profile": args.profile,
            "model_id": args.model,
        })
        resp = provider.complete(
            prompt="Write a one-sentence discharge summary for a 65yo male admitted for pneumonia, discharged after 7 days.",
            model=args.model,
            max_tokens=200,
            system_prompt="You are a physician writing a discharge summary. Be concise.",
            temperature=0.3,
        )
        print(f"  OK: BedrockProvider returned {len(resp.text)} chars in {resp.latency_ms}ms")
        print(f"      tokens: in={resp.input_tokens} out={resp.output_tokens}")
        print(f"      text: {resp.text[:200]!r}")
    except Exception as e:
        print(f"  FAIL: {type(e).__name__}: {e}")
        ok = False

    # ---- Check 6: clinosim LLMService with PromptRegistry ----
    print("\n" + "=" * 60)
    print("Check 6: clinosim LLMService + PromptRegistry (discharge_summary)")
    print("=" * 60)
    try:
        from clinosim.modules.llm_service.engine import (
            ClinicalEventData,
            LLMService,
            LLMTaskType,
            PatientSummary,
        )
        from clinosim.modules.llm_service.providers.bedrock import BedrockProvider

        provider = BedrockProvider({
            "region": args.region,
            "profile": args.profile,
            "model_id": args.model,
        })
        svc = LLMService(
            mode="llm",
            narrative_provider=provider,
            narrative_model_map={"medium": args.model},
            provider_name_narrative="bedrock",
        )
        ps = PatientSummary(age=72, sex="Male", country="US",
                            current_diagnosis="Bacterial pneumonia")
        event = ClinicalEventData(patient_summary=ps, event_data={}, language="en")
        variables = {
            "age": 72, "sex": "Male",
            "admission_date": "2026-03-01", "discharge_date": "2026-03-14",
            "los_days": 14, "disposition": "home",
            "attending_physician": "Dr. Smith",
            "chief_complaint": "Fever and productive cough for 3 days",
            "past_medical_history": ["Hypertension", "Type 2 diabetes"],
            "admission_diagnosis": "Bacterial pneumonia",
            "discharge_diagnoses": ["Bacterial pneumonia (resolved)", "Hypertension", "Type 2 diabetes"],
            "hospital_course_bullets": [
                "Day 0: Admitted with fever 39.2C, WBC 15,200. Started IV ceftriaxone.",
                "Day 3: Defervescence. CRP trending down (180 → 45 mg/L).",
                "Day 7: Switched to oral amoxicillin. Ambulatory.",
                "Day 14: Discharged home in stable condition.",
            ],
            "procedures_performed": "(none)",
            "discharge_medications": [
                "Amoxicillin 500mg PO TID x 7 days",
                "Metformin 500mg PO BID (home med)",
                "Lisinopril 10mg PO daily (home med)",
            ],
        }

        resp = svc.generate(LLMTaskType.DISCHARGE_SUMMARY, event, variables=variables)
        print(f"  OK: source={resp.source} model={resp.model}")
        print(f"      prompt_version={resp.prompt_version} tokens=in:{resp.input_tokens} out:{resp.output_tokens}")
        print(f"      text ({len(resp.text or '')} chars):")
        print()
        for line in (resp.text or "").split("\n")[:20]:
            print(f"      {line}")
        if (resp.text or "").count("\n") > 20:
            print(f"      ... [{(resp.text or '').count(chr(10)) - 20} more lines]")
    except Exception as e:
        print(f"  FAIL: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        ok = False

    # ---- Summary ----
    print("\n" + "=" * 60)
    if ok:
        print("ALL CHECKS PASSED — Bedrock is ready for clinosim narrative generation")
        print()
        print("Next steps:")
        print(f"  1. Generate CIF:   clinosim generate -o ./output -p 5000 --country US --format cif")
        print(f"  2. Run narratives: clinosim narrate --cif-dir ./output/cif \\")
        print(f"       --llm-config clinosim/config/llm_service.bedrock.yaml \\")
        print(f"       --version-id bedrock_en_v1")
        print(f"  3. Export FHIR:    clinosim export-fhir --cif-dir ./output/cif \\")
        print(f"       --narrative-version bedrock_en_v1")
    else:
        print("SOME CHECKS FAILED — review errors above")
    print("=" * 60)

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
