#!/usr/bin/env python3
"""Validate all 5 clinical document types via Bedrock.

Reads local CIF patient records, runs the exact same extractor and prompt
pipeline as `clinosim narrate`, calls Bedrock for each document, and saves
the full results (rendered prompt + LLM response) for review.

Usage (on EC2 with Bedrock access):
    python3 scripts/validate_5types_bedrock.py

Output:
    test_data/bedrock_5type_validation.txt
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from clinosim.codes import lookup as code_lookup
from clinosim.modules.llm_service.engine import (
    ClinicalEventData,
    LLMService,
    LLMTaskType,
    PatientSummary,
)
from clinosim.modules.llm_service.prompt_registry import PromptRegistry
from clinosim.modules.llm_service.providers.bedrock import BedrockProvider
from clinosim.modules.output.document_generator import (
    _build_admission_hp,
    _build_death_summary,
    _build_discharge_summary,
    _build_operative_note,
    _build_procedure_note,
    _format_guidance_for_prompt,
    _PROCEDURE_NOTE_TYPES,
    _SCT_SURGICAL,
)
from clinosim.modules.output.hospital_course_extractor import (
    extract_clinical_guidance,
    extract_hospital_course,
    extract_lab_trends,
    extract_treatment_timeline,
    format_lab_trends,
)


# CIF files to test (one per document type that needs a unique patient)
TEST_CASES = [
    # Round 4: Heart failure death, pulmonary embolism, hemorrhagic stroke+seizure
    {
        "cif_file": "test_data/smoke_patients/ENC-POP-001499-000111.json",
        "doc_types": ["admission_hp", "discharge_summary", "death_summary"],
        "label": "Heart failure death, 73yo F, 5 home meds (HF+DM+HTN+dyslipidemia+AFib)",
    },
    {
        "cif_file": "test_data/smoke_patients/ENC-POP-001266-000078.json",
        "doc_types": ["admission_hp", "procedure_note", "discharge_summary"],
        "label": "Pulmonary embolism, 82yo F, central line, 1 home med",
    },
    {
        "cif_file": "test_data/smoke_patients/ENC-POP-000767-000035.json",
        "doc_types": ["admission_hp", "discharge_summary"],
        "label": "Hemorrhagic stroke, 51yo M, seizure complication, 1 home med",
    },
]


def main() -> None:
    output_path = Path("test_data/bedrock_5type_validation.txt")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Build Bedrock-backed LLMService
    provider = BedrockProvider({
        "region": "us-east-1",
        "model_id": "us.anthropic.claude-sonnet-4-20250514-v1:0",
    })
    llm = LLMService(
        mode="llm",
        narrative_provider=provider,
        narrative_model_map={"medium": "us.anthropic.claude-sonnet-4-20250514-v1:0"},
        provider_name_narrative="bedrock",
    )
    registry = PromptRegistry()

    lines: list[str] = []

    def out(text: str = "") -> None:
        print(text)
        lines.append(text)

    out("=" * 70)
    out(f"  5-Type Bedrock Clinical Document Validation")
    out(f"  Date: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}")
    out("=" * 70)

    for case in TEST_CASES:
        cif_path = Path(case["cif_file"])
        if not cif_path.exists():
            out(f"\n  SKIP: {cif_path} not found")
            continue

        record = json.loads(cif_path.read_text())
        encounter = record["encounters"][0]
        patient = record.get("patient", {})

        # Shared enrichment
        guidance = extract_clinical_guidance(record)
        lab_trends = extract_lab_trends(record)
        lab_trend_bullets = format_lab_trends(lab_trends)
        treatment_timeline = extract_treatment_timeline(record)
        facts = extract_hospital_course(record, "en")
        course_bullets = [f.description for f in facts]
        enrichment = {
            "guidance": guidance,
            "lab_trends": lab_trends,
            "lab_trend_bullets": lab_trend_bullets,
            "treatment_timeline": treatment_timeline,
        }

        out(f"\n{'=' * 70}")
        out(f"  PATIENT: {case['label']}")
        out(f"  File: {case['cif_file']}")
        out(f"  ID: {patient.get('patient_id', '?')}  Age: {patient.get('age', '?')}  Sex: {patient.get('sex', '?')}")
        out(f"  Ground truth: {(record.get('condition_event') or {}).get('ground_truth_diseases', [])}")
        out(f"  Deceased: {record.get('deceased', False)}")
        out(f"  Procedures: {len(record.get('procedures', []))}")
        out(f"{'=' * 70}")

        out(f"\n  --- Enrichment Data (from extractor) ---")
        out(f"  Clinical guidance:")
        for k, v in guidance.items():
            out(f"    {k}: {v}")
        out(f"  Lab trends:")
        for b in lab_trend_bullets:
            out(f"    {b}")
        out(f"  Treatment timeline ({len(treatment_timeline)} events):")
        for t in treatment_timeline[:8]:
            out(f"    {t}")
        if len(treatment_timeline) > 8:
            out(f"    ... and {len(treatment_timeline) - 8} more")
        out(f"  Hospital course ({len(course_bullets)} facts):")
        for c in course_bullets:
            out(f"    {c}")

        for doc_type in case["doc_types"]:
            out(f"\n  {'=' * 60}")
            out(f"  DOCUMENT: {doc_type}")
            out(f"  {'=' * 60}")

            # Build the document using the EXACT same code path as clinosim narrate
            try:
                if doc_type == "admission_hp":
                    doc = _build_admission_hp(record, encounter, llm, "en", enrichment)
                elif doc_type == "discharge_summary":
                    doc = _build_discharge_summary(record, encounter, course_bullets, llm, "en", enrichment)
                elif doc_type == "death_summary":
                    doc = _build_death_summary(record, encounter, course_bullets, llm, "en", enrichment)
                elif doc_type == "operative_note":
                    surgeries = [p for p in record.get("procedures", [])
                                 if isinstance(p, dict) and p.get("category_code") == _SCT_SURGICAL]
                    if surgeries:
                        doc = _build_operative_note(surgeries[0], record, encounter, llm, "en", index=1, enrichment=enrichment)
                    else:
                        out(f"    (no surgical procedure found)")
                        continue
                elif doc_type == "procedure_note":
                    invasive = [p for p in record.get("procedures", [])
                                if isinstance(p, dict)
                                and p.get("category_code") != _SCT_SURGICAL
                                and p.get("procedure_type") in _PROCEDURE_NOTE_TYPES]
                    if invasive:
                        doc = _build_procedure_note(invasive[0], record, encounter, llm, "en", enrichment=enrichment)
                    else:
                        out(f"    (no invasive bedside procedure found)")
                        continue
                else:
                    out(f"    (unknown doc type)")
                    continue
            except Exception as e:
                out(f"    ERROR: {type(e).__name__}: {e}")
                import traceback
                out(traceback.format_exc())
                continue

            out(f"  LOINC:      {doc.loinc_code}")
            out(f"  Source:     {doc.text_source} (model: {doc.llm_model})")
            out(f"  Tokens:    in={doc.llm_input_tokens}  out={doc.llm_output_tokens}")
            out(f"  Cache:     {doc.cache_hit}")
            out(f"  Fallback:  {doc.fallback_reason or '(none)'}")
            out(f"  {'─' * 60}")
            out(doc.text)

    # Summary
    out(f"\n{'=' * 70}")
    out(f"  Validation complete.")
    out(f"  Results: {output_path}")
    out(f"  Cost report: {llm.cost_report()}")
    out(f"  To share: git add {output_path} && git commit -m 'bedrock 5-type validation' && git push")
    out(f"{'=' * 70}")

    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
