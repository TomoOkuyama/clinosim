#!/usr/bin/env python3
"""Prepare A/B test prompts for JP narrative generation.

For each document that would be generated from a CIF record, captures TWO
versions of the LLM input:
  A: pre-localized enrichment (current behavior, language="ja" threaded
     through extract functions — drug names, procedures, events in JP)
  B: English enrichment (language="en" for extraction) + JP prompt template
     (LLM instructed to write in Japanese)

Both versions render the same ja/*.yaml prompt template (so system_prompt
says "write in Japanese") — only the variable values differ.

Output structure:
    test_data/ab_test/prompts/<encounter_id>/<task_type>.A.json
    test_data/ab_test/prompts/<encounter_id>/<task_type>.B.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from clinosim.modules.llm_service.prompt_registry import PromptRegistry
from clinosim.modules.output.document_generator import (
    _allergies,
    _build_hpi_summary,
    _format_guidance_for_prompt,
    _home_meds,
    _initial_labs,
    _localize_procedure,
    _pmh,
    _resolve_dx,
    _sex_label,
    _staff_name,
)
from clinosim.modules.output.hospital_course_extractor import (
    extract_clinical_guidance,
    extract_hospital_course,
    extract_lab_trends,
    extract_treatment_timeline,
    extract_vitals_snapshot,
    format_lab_trends,
    summarize_admission_vitals,
    summarize_discharge_medications,
    summarize_procedures,
    summarize_terminal_vitals,
)
from clinosim.codes import lookup as code_lookup


CIF_DIR = REPO_ROOT / "test_data" / "jp_compact2"
OUT_DIR = REPO_ROOT / "test_data" / "ab_test" / "prompts"


def _format_dt(dt_str: str) -> str:
    """Format ISO datetime to short form."""
    if not dt_str or not isinstance(dt_str, str):
        return ""
    return dt_str.replace("T", " ")[:16]


def _load_staff_map(cif_dir: Path) -> dict[str, str]:
    hosp = cif_dir / "hospital.json"
    if not hosp.exists():
        return {}
    import json as _json
    data = _json.loads(hosp.read_text(encoding="utf-8"))
    staff = {}
    for s in data.get("staff", []):
        sid = s.get("staff_id", "")
        name = s.get("name", "")
        if isinstance(name, dict):
            name = f'{name.get("family_name","")} {name.get("given_name","")}'.strip()
        if sid.startswith("DR-"):
            staff[sid] = f"{name}医師" if name else sid
        elif sid.startswith("NS-"):
            staff[sid] = f"{name}看護師" if name else sid
    return staff


def _build_admission_hp_vars(record, encounter, language_enrich, staff_map):
    patient = record.get("patient") or {}
    cd = record.get("clinical_diagnosis") or {}
    admit_dx = _resolve_dx(
        cd.get("admission_diagnosis_code", ""),
        cd.get("admission_diagnosis_system", "icd-10-cm"),
        language_enrich,
    )
    return {
        "age": patient.get("age", 0),
        "sex": _sex_label(patient.get("sex", ""), language_enrich),
        "admission_datetime": encounter.get("admission_datetime", ""),
        "admitting_physician": _staff_name(encounter.get("admitting_physician_id", ""), staff_map),
        "department": encounter.get("department_id", ""),
        "chief_complaint": encounter.get("chief_complaint", ""),
        "hpi_summary": _build_hpi_summary(encounter, patient, record, language_enrich),
        "past_medical_history": _pmh(patient, language_enrich),
        "home_medications": _home_meds(patient, language_enrich),
        "allergies": _allergies(patient, language_enrich),
        "admission_vitals": summarize_admission_vitals(record),
        "initial_labs": _initial_labs(record, language_enrich),
        "admission_diagnosis": admit_dx or "(under investigation)",
        "clinical_guidance": _format_guidance_for_prompt(
            extract_clinical_guidance(record, language_enrich), "admission_hp"
        ),
    }


def _build_discharge_summary_vars(record, encounter, language_enrich, staff_map):
    patient = record.get("patient") or {}
    cd = record.get("clinical_diagnosis") or {}
    adm_dx = _resolve_dx(
        cd.get("admission_diagnosis_code", ""),
        cd.get("admission_diagnosis_system", "icd-10-cm"),
        language_enrich,
    )
    dc_dx_code = cd.get("discharge_diagnosis_code", "") or cd.get("admission_diagnosis_code", "")
    dc_dx_system = cd.get("discharge_diagnosis_system", "") or cd.get("admission_diagnosis_system", "icd-10-cm")
    dc_dx = _resolve_dx(dc_dx_code, dc_dx_system, language_enrich)

    # Build enrichment consistent with language_enrich
    facts = extract_hospital_course(record, language_enrich)
    course_bullets = [f.description for f in facts]
    lab_trends = extract_lab_trends(record)
    lab_bullets = format_lab_trends(lab_trends, language_enrich)
    treat_timeline = extract_treatment_timeline(record, language_enrich)
    dc_meds = summarize_discharge_medications(record, language_enrich) or [
        ("(なし)" if language_enrich == "ja" else "(none)")
    ]
    procs_performed = summarize_procedures(record, language_enrich) or [
        ("(なし)" if language_enrich == "ja" else "(none)")
    ]

    enc = encounter
    admission_date = (enc.get("admission_datetime", "") or "")[:10]
    discharge_date = (enc.get("discharge_datetime", "") or "")[:10]
    try:
        from datetime import datetime as _dt
        los_days = (
            _dt.fromisoformat(enc["discharge_datetime"])
            - _dt.fromisoformat(enc["admission_datetime"])
        ).days
    except Exception:
        los_days = 0
    disposition = enc.get("discharge_disposition", "home")

    return {
        "age": patient.get("age", 0),
        "sex": _sex_label(patient.get("sex", ""), language_enrich),
        "admission_date": admission_date,
        "discharge_date": discharge_date,
        "los_days": los_days,
        "disposition": disposition,
        "attending_physician": _staff_name(enc.get("attending_physician_id", ""), staff_map),
        "chief_complaint": enc.get("chief_complaint", ""),
        "past_medical_history": _pmh(patient, language_enrich),
        "admission_diagnosis": adm_dx or "(not specified)",
        "discharge_diagnoses": [dc_dx] if dc_dx else ["(uncertain)"],
        "hospital_course_bullets": course_bullets,
        "lab_trends_summary": lab_bullets,
        "treatment_timeline": treat_timeline,
        "procedures_performed": procs_performed,
        "discharge_medications": dc_meds,
        "clinical_guidance": _format_guidance_for_prompt(
            extract_clinical_guidance(record, language_enrich), "discharge_summary"
        ),
    }


def main():
    patient_files = sorted((CIF_DIR / "structural" / "patients").glob("*.json"))
    staff_map = _load_staff_map(CIF_DIR)

    registry = PromptRegistry(
        REPO_ROOT / "clinosim" / "modules" / "llm_service" / "prompts"
    )

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    generated = 0

    for pf in patient_files:
        record = json.loads(pf.read_text(encoding="utf-8"))
        enc = (record.get("encounters") or [{}])[0]
        if enc.get("encounter_type") != "inpatient":
            continue
        encounter_id = enc.get("encounter_id", "")
        enc_dir = OUT_DIR / encounter_id
        enc_dir.mkdir(parents=True, exist_ok=True)

        # Generate 2 doc types per patient to keep cost manageable
        tasks = {
            "admission_hp": _build_admission_hp_vars,
            "discharge_summary": _build_discharge_summary_vars,
        }

        for task_name, builder in tasks.items():
            for variant_label, lang_enrich in (("A", "ja"), ("B", "en")):
                variables = builder(record, enc, lang_enrich, staff_map)
                # Prompt template is ALWAYS ja (output language instruction)
                spec = registry.get(task_name, language="ja")
                sys_p, user_p = spec.render(variables)

                prompt_blob = {
                    "encounter_id": encounter_id,
                    "task_type": task_name,
                    "variant": variant_label,
                    "description": (
                        "A=pre-localized JP enrichment" if variant_label == "A"
                        else "B=English enrichment + JP prompt"
                    ),
                    "language_enrichment": lang_enrich,
                    "language_output": "ja",
                    "prompt_version": spec.version,
                    "max_tokens": spec.max_tokens,
                    "temperature": spec.temperature,
                    "system_prompt": sys_p,
                    "user_prompt": user_p,
                }
                out_file = enc_dir / f"{task_name}.{variant_label}.json"
                out_file.write_text(
                    json.dumps(prompt_blob, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                generated += 1

    print(f"Generated {generated} prompt files under {OUT_DIR}")
    print(f"A (pre-localized) + B (English) × {generated // 2} documents")


if __name__ == "__main__":
    main()
