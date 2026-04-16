"""Stage 2: Clinical document generator (Tier A + B).

Reads structural CIF patient records, builds ``ClinicalDocument`` stubs for
each applicable document type, calls ``LLMService`` to fill the text, and
writes the narrative CIF under:

    <cif_dir>/narratives/<version_id>/
        manifest.json
        documents/
            ENC-POP-000005-0001/
                discharge_summary.json
                death_summary.json        (if deceased)
                admission_hp.json
                operative_note_001.json   (one per surgery)
                procedure_note_central_line.json
                ...

Document scope (Milestone 1 / Tier A+B):
  A. discharge_summary, death_summary, operative_note  (clinically mandatory)
  B. admission_hp, procedure_note (major invasive only)
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from clinosim.codes import lookup as code_lookup
from clinosim.modules.llm_service.engine import (
    ClinicalEventData,
    LLMResponse,
    LLMService,
    LLMTaskType,
    PatientSummary,
    loinc_for,
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
from clinosim.types.clinical import ClinicalDocument

# Only these bedside procedures produce a Procedure Note (Tier B).
# Everything else (urinary_catheter, NG tube, echo, transfusion, dialysis,
# arterial_line, wound_debridement) is folded into nursing or ancillary records.
_PROCEDURE_NOTE_TYPES = {
    "central_line",
    "lumbar_puncture",
    "thoracentesis",
    "paracentesis",
    "chest_tube",
    "intubation",
    "bronchoscopy",
    "cardioversion",
}

# SNOMED category code for surgical procedures (used by Operative Note).
_SCT_SURGICAL = "387713003"


# ============================================================
# Public entry point
# ============================================================


def generate_documents(
    cif_dir: str | Path,
    llm_service: LLMService,
    version_id: str | None = None,
    language: str = "en",
    tasks: Iterable[str] | None = None,
) -> str:
    """Generate Tier A+B clinical documents for all patients in the CIF.

    Args:
        cif_dir: path to a ``cif/`` directory (contains ``structural/``).
        llm_service: pre-built LLMService (template, LLM, etc.).
        version_id: narrative version directory name. Auto-generated if None.
        language: "en" or "ja" — selected prompt template language.
        tasks: optional subset of LLMTaskType values to generate
            (default = all Tier A+B types).

    Returns:
        The version_id used.
    """
    cif_dir = Path(cif_dir)
    structural_dir = cif_dir / "structural" / "patients"
    if not structural_dir.is_dir():
        raise FileNotFoundError(
            f"CIF structural/patients directory not found: {structural_dir}"
        )

    version_id = version_id or f"narrative_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    narrative_root = cif_dir / "narratives" / version_id
    documents_root = narrative_root / "documents"
    documents_root.mkdir(parents=True, exist_ok=True)

    enabled_tasks = _resolve_enabled_tasks(tasks)

    # Load staff name map from hospital.json (staff_id → display name)
    staff_names: dict[str, str] = {}
    hospital_path = cif_dir / "hospital.json"
    if hospital_path.exists():
        hospital_data = json.loads(hospital_path.read_text(encoding="utf-8"))
        is_jp = language == "ja"
        for s in hospital_data.get("staff", []):
            sid = s.get("staff_id", "")
            name = s.get("name", "")
            if sid and name:
                if sid.startswith("DR-"):
                    staff_names[sid] = f"{name}医師" if is_jp else f"Dr. {name}"
                elif sid.startswith("NS-"):
                    staff_names[sid] = f"{name}看護師" if is_jp else f"RN {name}"
                else:
                    staff_names[sid] = name

    patient_count = 0
    doc_counts: dict[str, int] = {}

    # Count total files for progress display
    all_files = sorted(f for f in os.listdir(structural_dir) if f.endswith(".json"))
    total_files = len(all_files)

    for file_idx, filename in enumerate(all_files):
        with open(structural_dir / filename, encoding="utf-8") as f:
            record = json.load(f)

        docs = _generate_for_record(record, llm_service, language, enabled_tasks, staff_names)
        if not docs:
            continue

        # Progress display
        total_docs = sum(doc_counts.values())
        if patient_count % 10 == 0 or file_idx == total_files - 1:
            print(
                f"  Narrating {file_idx + 1}/{total_files} files, "
                f"{patient_count} patients, {total_docs} documents...",
                flush=True,
            )

        enc_id = _encounter_id(record)
        enc_dir = documents_root / enc_id
        enc_dir.mkdir(parents=True, exist_ok=True)
        for doc in docs:
            out_path = enc_dir / _doc_filename(doc)
            out_path.write_text(
                json.dumps(asdict(doc), indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            doc_counts[doc.task_type] = doc_counts.get(doc.task_type, 0) + 1

        patient_count += 1

    # Write manifest
    manifest = {
        "version_id": version_id,
        "generated_at": datetime.now().isoformat(),
        "language": language,
        "llm_mode": llm_service.mode,
        "llm_cost_report": llm_service.cost_report(),
        "patient_count": patient_count,
        "document_counts_by_type": doc_counts,
        "total_documents": sum(doc_counts.values()),
        "enabled_tasks": sorted(t.value for t in enabled_tasks),
    }
    (narrative_root / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # Pointer to current version (for export-fhir convenience)
    (cif_dir / "narratives" / "current_version.txt").write_text(version_id)
    return version_id


# ============================================================
# Per-record generation
# ============================================================


def _generate_for_record(
    record: dict[str, Any],
    llm: LLMService,
    language: str,
    enabled: set[LLMTaskType],
    staff_names: dict[str, str] | None = None,
) -> list[ClinicalDocument]:
    encounters = record.get("encounters") or []
    if not encounters:
        return []
    encounter = encounters[0]
    # Only inpatient encounters generate full clinical documents.
    # Outpatient / ED visits are out of scope for Milestone 1.
    if encounter.get("encounter_type") != "inpatient":
        return []

    patient = record.get("patient") or {}
    patient_id = patient.get("patient_id", "")
    encounter_id = encounter.get("encounter_id", "")
    if not patient_id or not encounter_id:
        return []

    # Skip still-admitted in-progress encounters (no discharge content possible)
    if encounter.get("status") == "in-progress":
        return []

    docs: list[ClinicalDocument] = []
    facts = extract_hospital_course(record, language)
    course_bullets = [f.description for f in facts]
    deceased = bool(record.get("deceased"))

    # Pre-compute shared enrichment data (used across multiple document types)
    guidance = extract_clinical_guidance(record, language)
    lab_trends = extract_lab_trends(record)
    lab_trend_bullets = format_lab_trends(lab_trends, language)
    treatment_timeline = extract_treatment_timeline(record)

    # Shared context dict passed to all builders
    enrichment = {
        "guidance": guidance,
        "lab_trends": lab_trends,
        "lab_trend_bullets": lab_trend_bullets,
        "treatment_timeline": treatment_timeline,
    }

    # Name resolver
    _sn = staff_names

    # --- Admission H&P (Tier B) ---
    if LLMTaskType.ADMISSION_HP in enabled:
        docs.append(_build_admission_hp(record, encounter, llm, language, enrichment, _sn))

    # --- Operative Note (Tier A) — one per surgery ---
    if LLMTaskType.OPERATIVE_NOTE in enabled:
        for i, proc in enumerate(record.get("procedures") or []):
            if not isinstance(proc, dict):
                continue
            if proc.get("category_code") != _SCT_SURGICAL:
                continue
            docs.append(_build_operative_note(proc, record, encounter, llm, language, index=i + 1, enrichment=enrichment, staff_names=_sn))

    # --- Procedure Note (Tier B) — invasive bedside only ---
    if LLMTaskType.PROCEDURE_NOTE in enabled:
        for proc in record.get("procedures") or []:
            if not isinstance(proc, dict):
                continue
            if proc.get("category_code") == _SCT_SURGICAL:
                continue
            if proc.get("procedure_type") not in _PROCEDURE_NOTE_TYPES:
                continue
            docs.append(_build_procedure_note(proc, record, encounter, llm, language, enrichment=enrichment, staff_names=_sn))

    # --- Discharge Summary (Tier A) ---
    if LLMTaskType.DISCHARGE_SUMMARY in enabled:
        docs.append(
            _build_discharge_summary(record, encounter, course_bullets, llm, language, enrichment, _sn)
        )

    # --- Death Note (Tier A) — only for deceased inpatients ---
    if deceased and LLMTaskType.DEATH_SUMMARY in enabled:
        docs.append(_build_death_summary(record, encounter, course_bullets, llm, language, enrichment, _sn))

    return docs


# ============================================================
# Per-document builders
# ============================================================


def _build_discharge_summary(
    record: dict[str, Any],
    encounter: dict[str, Any],
    course_bullets: list[str],
    llm: LLMService,
    language: str,
    enrichment: dict[str, Any] | None = None,
    staff_names: dict[str, str] | None = None,
) -> ClinicalDocument:
    patient = record.get("patient") or {}
    cd = record.get("clinical_diagnosis") or {}

    admission_dt = encounter.get("admission_datetime", "")
    discharge_dt = encounter.get("discharge_datetime", "")
    los_days = _los_days(admission_dt, discharge_dt)

    discharge_meds = summarize_discharge_medications(record, language)
    procedures_text = summarize_procedures(record, language)

    admit_dx_name = _resolve_dx(
        cd.get("admission_diagnosis_code", ""),
        cd.get("admission_diagnosis_system", "icd-10-cm"),
        language,
    )
    final_dx_name = _resolve_dx(
        cd.get("discharge_diagnosis_code", ""),
        cd.get("discharge_diagnosis_system", "icd-10-cm"),
        language,
    )

    variables = {
        "age": patient.get("age", 0),
        "sex": _sex_label(patient.get("sex", ""), language),
        "admission_date": _date_only(admission_dt),
        "discharge_date": _date_only(discharge_dt),
        "los_days": los_days,
        "disposition": encounter.get("discharge_disposition", "home"),
        "attending_physician": _staff_name(encounter.get("attending_physician_id", ""), staff_names),
        "chief_complaint": encounter.get("chief_complaint", ""),
        "past_medical_history": _pmh(patient, language),
        "admission_diagnosis": admit_dx_name or "(undiagnosed)",
        "discharge_diagnoses": [final_dx_name] if final_dx_name else ["(unknown)"],
        "hospital_course_bullets": course_bullets,
        "procedures_performed": procedures_text or "(none)",
        "discharge_medications": discharge_meds or ["(none)"],
        "lab_trends_summary": (enrichment or {}).get("lab_trend_bullets", []),
        "treatment_timeline": (enrichment or {}).get("treatment_timeline", []),
        "clinical_guidance": _format_guidance_for_prompt(
            (enrichment or {}).get("guidance", {}), "discharge_summary"
        ),
    }

    stub = _make_stub(
        task_type=LLMTaskType.DISCHARGE_SUMMARY,
        patient_id=patient.get("patient_id", ""),
        encounter_id=encounter.get("encounter_id", ""),
        authored_datetime=discharge_dt or admission_dt,
        period_start=admission_dt,
        period_end=discharge_dt,
        language=language,
        author_practitioner_id=encounter.get("discharging_physician_id")
        or encounter.get("attending_physician_id", ""),
        source_record=record,
    )
    return _fill_text(stub, llm, variables)


def _build_death_summary(
    record: dict[str, Any],
    encounter: dict[str, Any],
    course_bullets: list[str],
    llm: LLMService,
    language: str,
    enrichment: dict[str, Any] | None = None,
    staff_names: dict[str, str] | None = None,
) -> ClinicalDocument:
    patient = record.get("patient") or {}
    cd = record.get("clinical_diagnosis") or {}

    admission_dt = encounter.get("admission_datetime", "")
    discharge_dt = encounter.get("discharge_datetime", "")
    los_days = _los_days(admission_dt, discharge_dt)

    primary_dx = _resolve_dx(
        cd.get("discharge_diagnosis_code", "")
        or cd.get("admission_diagnosis_code", ""),
        cd.get("discharge_diagnosis_system", "icd-10-cm"),
        language,
    )
    admit_dx = _resolve_dx(
        cd.get("admission_diagnosis_code", ""),
        cd.get("admission_diagnosis_system", "icd-10-cm"),
        language,
    )

    variables = {
        "age": patient.get("age", 0),
        "sex": _sex_label(patient.get("sex", ""), language),
        "admission_date": _date_only(admission_dt),
        "death_datetime": discharge_dt,
        "los_days": los_days,
        "attending_physician": _staff_name(encounter.get("attending_physician_id", ""), staff_names),
        "admission_diagnosis": admit_dx or "(undiagnosed)",
        "primary_diagnosis": primary_dx or "(unknown)",
        "past_medical_history": _pmh(patient, language),
        "hospital_course_bullets": course_bullets,
        "terminal_findings": summarize_terminal_vitals(record),
        "complications": record.get("complications_occurred") or ["(none documented)"],
        "lab_trends_summary": (enrichment or {}).get("lab_trend_bullets", []),
        "treatment_timeline": (enrichment or {}).get("treatment_timeline", []),
        "clinical_guidance": _format_guidance_for_prompt(
            (enrichment or {}).get("guidance", {}), "death_summary"
        ),
    }

    stub = _make_stub(
        task_type=LLMTaskType.DEATH_SUMMARY,
        patient_id=patient.get("patient_id", ""),
        encounter_id=encounter.get("encounter_id", ""),
        authored_datetime=discharge_dt or admission_dt,
        period_start=admission_dt,
        period_end=discharge_dt,
        language=language,
        author_practitioner_id=encounter.get("attending_physician_id", ""),
        source_record=record,
    )
    return _fill_text(stub, llm, variables)


def _build_admission_hp(
    record: dict[str, Any],
    encounter: dict[str, Any],
    llm: LLMService,
    language: str,
    enrichment: dict[str, Any] | None = None,
    staff_names: dict[str, str] | None = None,
) -> ClinicalDocument:
    patient = record.get("patient") or {}
    cd = record.get("clinical_diagnosis") or {}

    admit_dx = _resolve_dx(
        cd.get("admission_diagnosis_code", ""),
        cd.get("admission_diagnosis_system", "icd-10-cm"),
        language,
    )

    variables = {
        "age": patient.get("age", 0),
        "sex": _sex_label(patient.get("sex", ""), language),
        "admission_datetime": encounter.get("admission_datetime", ""),
        "admitting_physician": _staff_name(encounter.get("admitting_physician_id", ""), staff_names),
        "department": encounter.get("department_id", ""),
        "chief_complaint": encounter.get("chief_complaint", ""),
        "hpi_summary": _build_hpi_summary(encounter, patient, record, language),
        "past_medical_history": _pmh(patient, language),
        "home_medications": _home_meds(patient),
        "allergies": _allergies(patient),
        "admission_vitals": summarize_admission_vitals(record),
        "initial_labs": _initial_labs(record, language),
        "admission_diagnosis": admit_dx or "(under investigation)",
        # Clinical guidance: helps LLM write a realistic differential that leans
        # toward the actual diagnosis, without stating it as confirmed.
        "clinical_guidance": _format_guidance_for_prompt(
            (enrichment or {}).get("guidance", {}), "admission_hp"
        ),
    }

    stub = _make_stub(
        task_type=LLMTaskType.ADMISSION_HP,
        patient_id=patient.get("patient_id", ""),
        encounter_id=encounter.get("encounter_id", ""),
        authored_datetime=encounter.get("admission_datetime", ""),
        period_start=encounter.get("admission_datetime", ""),
        period_end=encounter.get("admission_datetime", ""),
        language=language,
        author_practitioner_id=encounter.get("admitting_physician_id", ""),
        source_record=record,
    )
    return _fill_text(stub, llm, variables)


def _build_operative_note(
    proc: dict[str, Any],
    record: dict[str, Any],
    encounter: dict[str, Any],
    llm: LLMService,
    language: str,
    index: int,
    enrichment: dict[str, Any] | None = None,
    staff_names: dict[str, str] | None = None,
) -> ClinicalDocument:
    patient_id = (record.get("patient") or {}).get("patient_id", "")
    body_site_code = proc.get("body_site_code", "")
    body_site_display = (
        code_lookup("snomed-ct", body_site_code, language)
        if body_site_code
        else "(unspecified)"
    )
    variables = {
        "surgery_date": _format_dt(proc.get("start_datetime")),
        "procedure_name": proc.get("procedure_name", ""),
        "procedure_code": proc.get("procedure_code", ""),
        "preop_diagnosis": proc.get("preop_diagnosis", ""),
        "postop_diagnosis": proc.get("postop_diagnosis", ""),
        "surgeon": _staff_name(proc.get("primary_surgeon_id", ""), staff_names),
        "assistants": [_staff_name(a, staff_names) for a in (proc.get("assistant_ids") or [])] or ["(none)"],
        "anesthesiologist": _staff_name(proc.get("anesthesiologist_id", ""), staff_names),
        "anesthesia_type": proc.get("anesthesia_type", ""),
        "asa_class": proc.get("asa_class", ""),
        "duration_minutes": proc.get("duration_minutes", 0),
        "estimated_blood_loss_ml": proc.get("estimated_blood_loss_ml", 0),
        "body_site": body_site_display,
        "approach": proc.get("approach") or "(as per standard technique)",
        "implants_used": proc.get("implants_used") or ["(none)"],
        "specimens_sent": proc.get("specimens_sent") or ["(none)"],
        "intraop_complications": proc.get("intraop_complications") or ["(none)"],
        "outcome": _outcome_label(proc.get("outcome_code", ""), language),
        # Pre-op vitals (closest to surgery day)
        "preop_vitals": extract_vitals_snapshot(
            record,
            target_day=_day_offset_from_encounter(encounter, proc.get("start_datetime")),
        ),
        "clinical_guidance": _format_guidance_for_prompt(
            (enrichment or {}).get("guidance", {}), "operative_note"
        ),
    }

    stub = _make_stub(
        task_type=LLMTaskType.OPERATIVE_NOTE,
        patient_id=patient_id,
        encounter_id=encounter.get("encounter_id", ""),
        authored_datetime=proc.get("end_datetime", "") or proc.get("start_datetime", ""),
        period_start=proc.get("start_datetime", ""),
        period_end=proc.get("end_datetime", ""),
        language=language,
        author_practitioner_id=proc.get("primary_surgeon_id", ""),
        related_procedure_id=proc.get("procedure_id", ""),
        source_record=record,
        variant_suffix=f"{index:03d}",
    )
    return _fill_text(stub, llm, variables)


def _build_procedure_note(
    proc: dict[str, Any],
    record: dict[str, Any],
    encounter: dict[str, Any],
    llm: LLMService,
    language: str,
    enrichment: dict[str, Any] | None = None,
    staff_names: dict[str, str] | None = None,
) -> ClinicalDocument:
    patient_id = (record.get("patient") or {}).get("patient_id", "")
    body_site_code = proc.get("body_site_code", "")
    body_site_display = (
        code_lookup("snomed-ct", body_site_code, language)
        if body_site_code
        else "(unspecified)"
    )
    ptype = proc.get("procedure_type", "")

    variables = {
        "procedure_date": _format_dt(proc.get("start_datetime")),
        "procedure_name": proc.get("procedure_name", ""),
        "procedure_code": proc.get("procedure_code", ""),
        "operator": _staff_name(proc.get("primary_surgeon_id", "") or encounter.get("attending_physician_id", ""), staff_names),
        "indication": proc.get("preop_diagnosis") or encounter.get("chief_complaint", ""),
        "body_site": body_site_display,
        "anesthesia_type": proc.get("anesthesia_type", "local"),
        "duration_minutes": proc.get("duration_minutes", 30),
        "findings": "(see procedure description)",
        "specimens_obtained": proc.get("specimens_sent") or ["(none)"],
        "complications": proc.get("intraop_complications") or ["(none)"],
        "outcome": _outcome_label(proc.get("outcome_code", ""), language),
        "clinical_guidance": _format_guidance_for_prompt(
            (enrichment or {}).get("guidance", {}), "procedure_note"
        ),
    }

    stub = _make_stub(
        task_type=LLMTaskType.PROCEDURE_NOTE,
        patient_id=patient_id,
        encounter_id=encounter.get("encounter_id", ""),
        authored_datetime=proc.get("end_datetime", "") or proc.get("start_datetime", ""),
        period_start=proc.get("start_datetime", ""),
        period_end=proc.get("end_datetime", ""),
        language=language,
        author_practitioner_id=proc.get("primary_surgeon_id", "")
        or encounter.get("attending_physician_id", ""),
        related_procedure_id=proc.get("procedure_id", ""),
        source_record=record,
        variant_suffix=ptype,
    )
    return _fill_text(stub, llm, variables)


# ============================================================
# Stub construction + text fill
# ============================================================


def _make_stub(
    *,
    task_type: LLMTaskType,
    patient_id: str,
    encounter_id: str,
    authored_datetime: str,
    period_start: str,
    period_end: str,
    language: str,
    author_practitioner_id: str,
    source_record: dict[str, Any],
    related_procedure_id: str = "",
    variant_suffix: str = "",
) -> ClinicalDocument:
    suffix = f"-{variant_suffix}" if variant_suffix else ""
    document_id = f"doc-{encounter_id}-{task_type.value}{suffix}"
    return ClinicalDocument(
        document_id=document_id,
        task_type=task_type.value,
        loinc_code=loinc_for(task_type) or "",
        patient_id=patient_id,
        encounter_id=encounter_id,
        author_practitioner_id=author_practitioner_id,
        related_procedure_id=related_procedure_id,
        authored_datetime=authored_datetime,
        period_start=period_start,
        period_end=period_end,
        language=language,
    )


def _fill_text(
    stub: ClinicalDocument,
    llm: LLMService,
    variables: dict[str, Any],
) -> ClinicalDocument:
    task_type = LLMTaskType(stub.task_type)
    ps = PatientSummary(
        age=variables.get("age", 0) or 0,
        sex=str(variables.get("sex", "")),
        country="US" if stub.language == "en" else "JP",
        current_diagnosis=str(variables.get("admission_diagnosis", "")),
    )
    event = ClinicalEventData(
        patient_summary=ps, event_data=variables, language=stub.language
    )
    resp: LLMResponse = llm.generate(task_type, event, variables=variables)

    stub.text = resp.text or ""
    stub.text_source = resp.source
    stub.llm_model = resp.model or ""
    stub.llm_provider = resp.provider or ""
    stub.llm_input_tokens = resp.input_tokens
    stub.llm_output_tokens = resp.output_tokens
    stub.prompt_version = resp.prompt_version
    stub.cache_hit = resp.cache_hit
    stub.generated_at = datetime.now().isoformat()
    stub.fallback_reason = resp.fallback_reason
    return stub


# ============================================================
# Small helpers
# ============================================================


def _resolve_enabled_tasks(tasks: Iterable[str] | None) -> set[LLMTaskType]:
    default = {
        LLMTaskType.DISCHARGE_SUMMARY,
        LLMTaskType.DEATH_SUMMARY,
        LLMTaskType.OPERATIVE_NOTE,
        LLMTaskType.ADMISSION_HP,
        LLMTaskType.PROCEDURE_NOTE,
    }
    if not tasks:
        return default
    out: set[LLMTaskType] = set()
    for t in tasks:
        try:
            task = LLMTaskType(t)
        except ValueError:
            continue
        if task in default:
            out.add(task)
    return out or default


def _doc_filename(doc: ClinicalDocument) -> str:
    """Filename within an encounter directory."""
    if doc.task_type == "operative_note":
        # Extract variant suffix from document_id
        suffix = doc.document_id.rsplit("-", 1)[-1]
        if suffix.isdigit():
            return f"operative_note_{suffix}.json"
        return "operative_note.json"
    if doc.task_type == "procedure_note":
        suffix = doc.document_id.rsplit("-", 1)[-1]
        return f"procedure_note_{suffix}.json"
    return f"{doc.task_type}.json"


def _encounter_id(record: dict[str, Any]) -> str:
    encounters = record.get("encounters") or []
    return encounters[0].get("encounter_id", "unknown") if encounters else "unknown"


def _parse_dt(s: Any) -> datetime | None:
    if not s:
        return None
    if isinstance(s, datetime):
        return s
    if isinstance(s, str):
        try:
            return datetime.fromisoformat(s)
        except ValueError:
            return None
    return None


def _los_days(admission: Any, discharge: Any) -> int:
    a = _parse_dt(admission)
    d = _parse_dt(discharge)
    if not a or not d:
        return 0
    return max(0, (d - a).days)


def _date_only(s: Any) -> str:
    dt = _parse_dt(s)
    return dt.strftime("%Y-%m-%d") if dt else str(s or "")


def _format_dt(s: Any) -> str:
    dt = _parse_dt(s)
    return dt.strftime("%Y-%m-%d %H:%M") if dt else str(s or "")


def _sex_label(sex: str, language: str) -> str:
    if language == "ja":
        return {"M": "男性", "F": "女性"}.get(sex, sex)
    return {"M": "Male", "F": "Female"}.get(sex, sex or "")


def _resolve_dx(code: str, system: str, language: str) -> str:
    if not code:
        return ""
    return code_lookup(system, code, language) or code


def _pmh(patient: dict[str, Any], language: str) -> list[str]:
    chronic = patient.get("chronic_conditions") or []
    out: list[str] = []
    for c in chronic:
        if not isinstance(c, dict):
            continue
        code = c.get("code") or ""
        if not code:
            continue
        name = code_lookup("icd-10-cm", code, language) or code
        out.append(name)
    return out or ["(none reported)"]


def _home_meds(patient: dict[str, Any]) -> list[str]:
    """Return English drug names. LLM handles translation based on prompt language."""
    meds = patient.get("current_medications") or patient.get("home_medications") or []
    out: list[str] = []
    for m in meds:
        if isinstance(m, dict):
            name = m.get("drug_name") or m.get("drug") or ""
            if name:
                out.append(name)
        elif isinstance(m, str):
            out.append(m)
    return out or ["(none)"]


def _allergies(patient: dict[str, Any]) -> list[str]:
    """Return English allergen names. LLM handles translation."""
    allergies = patient.get("allergies") or []
    out: list[str] = []
    for a in allergies:
        if isinstance(a, dict):
            name = a.get("substance") or a.get("name") or ""
            if name:
                out.append(name)
        elif isinstance(a, str):
            out.append(a)
    return out or ["NKDA"]


def _initial_labs(record: dict[str, Any], language: str = "en") -> list[str]:
    """Return the earliest abnormal labs as a bullet list.

    Checks both ``result.interpretation`` and ``result.flag`` since CIF
    may populate either field depending on the observation module version.
    """
    from clinosim.modules.output.hospital_course_extractor import (
        _JA_CONVERSION,
        _UNIT_MAP_JA,
    )

    orders = record.get("orders") or []
    abnormal: list[str] = []
    for o in orders[:30]:  # only look at the first batch
        if not isinstance(o, dict) or o.get("order_type") != "lab":
            continue
        result = o.get("result") or {}
        if not result:
            continue
        # Check both interpretation and flag fields
        flag = (
            result.get("interpretation")
            or result.get("flag")
            or ""
        ).upper()
        if flag in ("H", "L", "HH", "LL", "HU", "LU", "ABNORMAL"):
            name = result.get("lab_name") or o.get("display_name", "")
            val = result.get("value", "")
            unit = result.get("unit", "")
            # Convert units for Japanese locale (e.g. CRP mg/L → mg/dL)
            # This is a numerical transformation, not translation — kept code-side
            # per AD-42 because LLMs make arithmetic errors.
            if language == "ja" and isinstance(val, (int, float)):
                factor = _JA_CONVERSION.get(name, 1.0)
                if factor != 1.0:
                    val = round(val * factor, 2)
                    unit = _UNIT_MAP_JA.get(name, unit)
            abnormal.append(f"{name} {val} {unit} [{flag}]".strip())
    return abnormal[:8] or ["(all within normal limits)"]


def _build_hpi_summary(
    encounter: dict[str, Any],
    patient: dict[str, Any],
    record: dict[str, Any],
    language: str,
) -> str:
    """Build a richer HPI from chief complaint + admission vitals + initial labs.

    This avoids the HPI being a plain copy of the chief complaint, giving the
    LLM more context to work with.
    """
    parts: list[str] = []
    age = patient.get("age", 0)
    sex = _sex_label(patient.get("sex", ""), language)
    cc = encounter.get("chief_complaint", "")
    parts.append(f"{age}yo {sex} presenting with {cc}." if cc else f"{age}yo {sex}.")

    # Admission vitals
    vitals_str = summarize_admission_vitals(record)
    if vitals_str and vitals_str != "(not recorded)":
        parts.append(f"On arrival: {vitals_str}.")

    # Initial abnormal labs
    initial = _initial_labs(record, language)
    if initial and initial != ["(all within normal limits)"]:
        parts.append("Notable initial labs: " + "; ".join(initial[:4]) + ".")

    # Chronic conditions context
    pmh = _pmh(patient, language)
    if pmh and pmh != ["(none reported)"]:
        parts.append(f"PMH significant for {', '.join(pmh[:3])}.")

    return " ".join(parts)


def _day_offset_from_encounter(
    encounter: dict[str, Any], target_dt: Any
) -> int:
    """Compute hospital day from encounter admission to a target datetime."""
    admission = _parse_dt(encounter.get("admission_datetime"))
    target = _parse_dt(target_dt)
    if not admission or not target:
        return 0
    return max(0, (target - admission).days)


def _format_guidance_for_prompt(
    guidance: dict[str, Any], doc_type: str
) -> str:
    """Format clinical guidance as a hidden instruction block for the LLM.

    This appears as a ${clinical_guidance} variable in the prompt. The YAML
    system prompt instructs the LLM to use this for accuracy but never to
    state it directly in the output text.

    The format varies by document type to enforce temporal correctness:
    - admission_hp: "The actual diagnosis is X; write as if suspecting but
      not yet confirmed. Do NOT mention the confirmed diagnosis."
    - discharge_summary / death_summary: full context is allowed since these
      are written retrospectively.
    - operative_note / procedure_note: only procedure-relevant guidance.
    """
    if not guidance:
        return ""

    confirmed = guidance.get("confirmed_diagnosis", "")
    outcome = guidance.get("patient_outcome", "survived")
    severity = guidance.get("disease_severity", "")
    archetype = guidance.get("disease_archetype", "")
    dx_correct = guidance.get("diagnosis_correct", True)
    complications = guidance.get("complications", [])
    comp_str = ", ".join(complications) if complications else "none"

    if doc_type == "admission_hp":
        # Temporal constraint: Day 0 perspective — diagnosis NOT yet confirmed
        lines = [
            "[HIDDEN CLINICAL CONTEXT — for accuracy only, do NOT state in note]",
            f"Actual diagnosis (confirmed later): {confirmed}",
            f"Severity: {severity}",
            f"Patient outcome: {outcome}",
            "INSTRUCTION: Write the assessment as if you strongly suspect this "
            "diagnosis based on the presentation, but have NOT confirmed it yet. "
            "Include it high in the differential but do not state it as established. "
            "Do NOT mention the patient's eventual outcome or future events.",
        ]
        if not dx_correct:
            lines.append(
                "NOTE: The clinical team initially misdiagnosed this patient. "
                "The admission working diagnosis may differ from the actual disease."
            )
        return "\n".join(lines)

    if doc_type in ("discharge_summary", "death_summary"):
        # Retrospective — all context available
        lines = [
            "[HIDDEN CLINICAL CONTEXT — use for accurate clinical language]",
            f"Confirmed diagnosis: {confirmed}",
            f"Severity: {severity}",
            f"Clinical trajectory: {archetype}",
            f"Complications during stay: {comp_str}",
            f"Outcome: {outcome}",
        ]
        if not dx_correct:
            lines.append(
                "NOTE: Discharge diagnosis may not match the actual condition. "
                "The discharge note should reflect what the clinical team concluded."
            )
        return "\n".join(lines)

    if doc_type in ("operative_note", "procedure_note"):
        # Procedure-focused — only intraop-relevant context
        lines = [
            "[HIDDEN CLINICAL CONTEXT — for surgical detail accuracy]",
            f"Underlying diagnosis: {confirmed}",
            f"Severity: {severity}",
            f"Patient outcome: {outcome}",
            "INSTRUCTION: Write only what was observed during the procedure. "
            "Do NOT mention post-operative course or eventual outcome.",
        ]
        return "\n".join(lines)

    return ""


def _staff_name(staff_id: str, staff_names: dict[str, str] | None) -> str:
    """Resolve a staff ID to a display name. Falls back to the raw ID."""
    if not staff_names or not staff_id:
        return staff_id
    return staff_names.get(staff_id, staff_id)


def _outcome_label(code: str, language: str) -> str:
    if not code:
        return "(not documented)"
    return code_lookup("snomed-ct", code, language) or code
