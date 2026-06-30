"""Document module POST_ENCOUNTER enricher (Tier 1 #3 α-min-1 Task 8, AD-55).

Generates ClinicalDocument stubs (Stage 1 text via TemplateNarrativeGenerator)
and ClinicalImpressionRecord entries (daily working-diagnosis updates) for each
inpatient encounter.

Architecture:
- POST_ENCOUNTER order=95 (after imaging=90)
- Always-on Module (enabled=lambda c: True)
- Writes to record.documents (list[ClinicalDocument]) and
  record.extensions["clinical_impressions"] (list[ClinicalImpressionRecord])
- Locale gating via specs_for_country(country) — only applicable specs emitted
- All field reads via _o() for dict/dataclass dual access (silent-no-op defense)
- DOC_REFERENCE_ID_PREFIX + CLINICAL_IMPRESSION_ID_PREFIX from __init__.py
  are the writer-owned canonical constants (reader Task 9 imports from here)

Encounter type restriction (α-min-1 scope):
  INPATIENT / ICU / REHAB_INPATIENT → documents + impressions generated.
  OUTPATIENT / EMERGENCY / other types → skipped (future phases extend).

AD-32 snapshot compliance:
  DISCHARGE_SUMMARY (generation_frequency="discharge_once") is skipped when
  encounter.discharge_datetime is None (in-progress / snapshot truncation).

Stage 1 / Stage 2 lifecycle:
  Stage 1 (this module): text filled by TemplateNarrativeGenerator via
  LLMNarrativeGenerator wrapper (default OFF). ClinicalDocument.text_source
  = "template" for all Stage 1 documents.
  Stage 2 (future Task 15 / llm_service wiring): LLMNarrativeGenerator
  calls llm_service for llm_enabled_sections when CLINOSIM_NARRATIVE_LLM=on.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from clinosim.modules._shared import get_attr_or_key as _o
from clinosim.modules.disease.protocol import load_disease_protocol
from clinosim.modules.document import (
    CLINICAL_IMPRESSION_ID_PREFIX,
    DOC_REFERENCE_ID_PREFIX,
    specs_for_country,
)
from clinosim.modules.document.narrative.context import build_narrative_context
from clinosim.modules.document.narrative.llm_generator import LLMNarrativeGenerator
from clinosim.types.clinical import ClinicalDocument, ClinicalImpressionRecord
from clinosim.types.document import DocumentType, FormatType, NarrativeOutput

# α-min-1 scope: multi-day encounter types only.
# OUTPATIENT / EMERGENCY are future phases (β / γ).
_INPATIENT_ENCOUNTER_TYPES: frozenset[str] = frozenset({
    "inpatient",
    "icu",
    "rehab_inpatient",
})

_CANCELLED_STATUSES: frozenset[str] = frozenset({"cancelled"})


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _enc_type_value(enc_type: Any) -> str:
    """Normalize encounter_type to a lowercase string (enum or plain str)."""
    if enc_type is None:
        return ""
    # EncounterType(str, Enum) has a .value attribute; plain strings do not.
    if hasattr(enc_type, "value"):
        return str(enc_type.value).lower()
    return str(enc_type).lower()


def _enc_status_value(status: Any) -> str:
    """Normalize encounter status to a lowercase string."""
    if status is None:
        return ""
    if hasattr(status, "value"):
        return str(status.value).lower()
    return str(status).lower()


def _compute_los_days(
    admission_dt: datetime,
    discharge_dt: datetime | None,
    physiological_states: list[Any],
) -> int:
    """Compute length-of-stay in whole days.

    Completed encounter: difference between discharge and admission dates.
    In-progress encounter: use physiological_states count as proxy
    (one state per simulated day; len - 1 gives days elapsed) with a
    minimum of 1 so at least one PROGRESS_NOTE is emitted.
    """
    if discharge_dt is not None:
        return max(1, (discharge_dt.date() - admission_dt.date()).days)
    # In-progress: physiological_states has one entry per day + admission state
    n = len(physiological_states)
    return max(1, n - 1) if n > 1 else 1


def _narrative_to_text(output: NarrativeOutput, format_type: FormatType) -> str:
    """Flatten NarrativeOutput to a plain-text string for ClinicalDocument.text.

    FREE_TEXT  → output.raw_text (SOAP note or equivalent)
    COMPOSITION → sections concatenated as "[section_key]\\ntext" blocks
    QUESTIONNAIRE_RESPONSE → empty (structured; FHIR builder reads output.structured)
    """
    if format_type == FormatType.FREE_TEXT:
        return output.raw_text or ""
    if format_type == FormatType.COMPOSITION:
        parts = [f"[{k}]\n{v}" for k, v in output.sections.items() if v]
        return "\n\n".join(parts)
    return ""


# ---------------------------------------------------------------------------
# Enricher entry point
# ---------------------------------------------------------------------------


def document_enricher(ctx: Any) -> None:
    """POST_ENCOUNTER enricher: emit ClinicalDocument stubs + ClinicalImpressionRecords.

    Per inpatient encounter in ctx.records:
      - admission_once specs → 1 document at day 0
      - daily specs          → 1 document per LOS day
      - discharge_once specs → 1 document at day LOS-1, skipped if in-progress (AD-32)
      - ClinicalImpressionRecord → 1 per LOS day (always; locale-independent)

    EnricherContext interface (POST_ENCOUNTER):
      ctx.master_seed  — int
      ctx.records      — list with exactly 1 CIFPatientRecord-like object
      ctx.config       — SimulatorConfig-like; ctx.config.country = "us" | "jp"
    """
    country: str = str(_o(ctx.config, "country", "us") or "us").lower()
    specs = specs_for_country(country)
    lang = "ja" if country == "jp" else "en"
    generator = LLMNarrativeGenerator()

    for record in ctx.records:
        patient = _o(record, "patient", None)
        pid: str = (_o(patient, "patient_id", "") or "") if patient is not None else ""

        # Start from existing documents (preserves any pre-enricher stubs).
        documents: list[ClinicalDocument] = list(_o(record, "documents", []) or [])

        # Start from existing clinical_impressions (in case enricher is called >1x).
        raw_ext = _o(record, "extensions", {}) or {}
        clinical_impressions: list[ClinicalImpressionRecord] = list(
            raw_ext.get("clinical_impressions", [])
        )

        # Per-encounter sequential document sequence number.
        # Initialise per-record (not per-encounter) so IDs are globally unique
        # within the record regardless of encounter count.
        doc_seq = len(documents) + 1

        for encounter in _o(record, "encounters", []) or []:
            enc_type_val = _enc_type_value(_o(encounter, "encounter_type", None))
            if enc_type_val not in _INPATIENT_ENCOUNTER_TYPES:
                continue  # outpatient / emergency → future phases

            enc_status_val = _enc_status_value(_o(encounter, "status", None))
            if enc_status_val in _CANCELLED_STATUSES:
                continue  # AD-32: cancelled encounters produce no documents

            encounter_id: str = _o(encounter, "encounter_id", "") or ""
            # AD-16: datetime.now() is non-deterministic; use fixed sentinel as fallback.
            # In production every encounter has admission_datetime so this path is defensive.
            admission_dt: datetime = _o(encounter, "admission_datetime", None) or datetime(2000, 1, 1)
            discharge_dt: datetime | None = _o(encounter, "discharge_datetime", None)
            attending_id: str = _o(encounter, "attending_physician_id", "") or ""
            is_in_progress = discharge_dt is None

            physiological_states = list(_o(record, "physiological_states", []) or [])
            los_days = _compute_los_days(admission_dt, discharge_dt, physiological_states)

            # C-1 (Lens 4 I-2): resolve disease_protocol for this encounter so that
            # 32 disease YAML narrative blocks (hpi_template / physical_exam_findings /
            # discharge_instructions / chief_complaint) become reachable.
            # Source: _disease_id IPC key set by inpatient.py before POST_ENCOUNTER stage;
            # cleaned up after run_stage returns. Same access pattern as imaging_enricher.
            # Fallback: None (unchanged default) if disease_id is unknown or YAML missing.
            extensions_data = _o(record, "extensions", {}) or {}
            disease_id: str = (
                extensions_data.get("_disease_id", "")
                or _o(record, "disease_id", "")  # SimpleNamespace test fixture fallback
                or ""
            )
            disease_protocol: Any | None = None
            if disease_id:
                try:
                    disease_protocol = load_disease_protocol(disease_id)
                except (FileNotFoundError, Exception):
                    disease_protocol = None  # unknown disease_id → fall through to defaults

            # ── Document generation (per spec) ───────────────────────────────
            for spec in specs:
                freq = spec.generation_frequency
                doc_type = DocumentType(spec.type_key)

                if freq == "admission_once":
                    ctx_n = build_narrative_context(
                        record=record,
                        encounter=encounter,
                        document_type=doc_type,
                        day_index=0,
                        country=country,
                        los_days=los_days,
                        disease_protocol=disease_protocol,
                    )
                    output = generator.generate(ctx_n, spec)
                    documents.append(ClinicalDocument(
                        document_id=f"{DOC_REFERENCE_ID_PREFIX}{encounter_id}-{doc_seq:02d}",
                        task_type=spec.type_key,
                        loinc_code=spec.loinc_code,
                        patient_id=pid,
                        encounter_id=encounter_id,
                        author_practitioner_id=attending_id,
                        authored_datetime=admission_dt.isoformat(),
                        period_start=admission_dt.isoformat(),
                        period_end=admission_dt.isoformat(),
                        language=lang,
                        text=_narrative_to_text(output, spec.format_type),
                        text_source=output.metadata.get("generator", "template"),
                        sections=dict(output.sections),
                        format_type=spec.format_type.value,
                    ))
                    doc_seq += 1

                elif freq == "daily":
                    # Spec §7: PROGRESS_NOTE skipped for LOS=1 same-day encounters.
                    # A same-day admission/discharge has an H&P and discharge summary;
                    # a progress note in between is clinically redundant.
                    if los_days <= 1:
                        continue
                    for day in range(los_days):
                        day_dt = admission_dt + timedelta(days=day)
                        ctx_n = build_narrative_context(
                            record=record,
                            encounter=encounter,
                            document_type=doc_type,
                            day_index=day,
                            country=country,
                            los_days=los_days,
                            disease_protocol=disease_protocol,
                        )
                        output = generator.generate(ctx_n, spec)
                        documents.append(ClinicalDocument(
                            document_id=f"{DOC_REFERENCE_ID_PREFIX}{encounter_id}-{doc_seq:02d}",
                            task_type=spec.type_key,
                            loinc_code=spec.loinc_code,
                            patient_id=pid,
                            encounter_id=encounter_id,
                            author_practitioner_id=attending_id,
                            authored_datetime=day_dt.isoformat(),
                            period_start=day_dt.isoformat(),
                            period_end=day_dt.isoformat(),
                            language=lang,
                            text=_narrative_to_text(output, spec.format_type),
                            text_source=output.metadata.get("generator", "template"),
                            sections=dict(output.sections),
                            format_type=spec.format_type.value,
                        ))
                        doc_seq += 1

                elif freq == "discharge_once":
                    if is_in_progress:
                        continue  # AD-32: no discharge summary while encounter is open
                    end_dt = discharge_dt or admission_dt  # discharge_dt is non-None here
                    ctx_n = build_narrative_context(
                        record=record,
                        encounter=encounter,
                        document_type=doc_type,
                        day_index=los_days - 1,
                        country=country,
                        los_days=los_days,
                        disease_protocol=disease_protocol,
                    )
                    output = generator.generate(ctx_n, spec)
                    documents.append(ClinicalDocument(
                        document_id=f"{DOC_REFERENCE_ID_PREFIX}{encounter_id}-{doc_seq:02d}",
                        task_type=spec.type_key,
                        loinc_code=spec.loinc_code,
                        patient_id=pid,
                        encounter_id=encounter_id,
                        author_practitioner_id=attending_id,
                        authored_datetime=end_dt.isoformat(),
                        period_start=admission_dt.isoformat(),
                        period_end=end_dt.isoformat(),
                        language=lang,
                        text=_narrative_to_text(output, spec.format_type),
                        text_source=output.metadata.get("generator", "template"),
                        sections=dict(output.sections),
                        format_type=spec.format_type.value,
                    ))
                    doc_seq += 1

            # ── ClinicalImpression generation (per LOS day, always) ──────────
            for day in range(los_days):
                day_dt = admission_dt + timedelta(days=day)
                # AD-32: the last day of an in-progress encounter is "in-progress"
                # (encounter still open; prior days remain "completed").
                last_day_of_in_progress = is_in_progress and (day == los_days - 1)
                clinical_impressions.append(ClinicalImpressionRecord(
                    impression_id=f"{CLINICAL_IMPRESSION_ID_PREFIX}{encounter_id}-{day}",
                    encounter_id=encounter_id,
                    date=day_dt.date(),
                    day_index=day,
                    description=f"Day {day + 1} clinical assessment",
                    practitioner_id=attending_id,
                    is_in_progress=last_day_of_in_progress,
                ))

        # ── Write back to record ─────────────────────────────────────────────
        # documents: typed field on CIFPatientRecord; assignable on both dict and object.
        if isinstance(record, dict):
            record["documents"] = documents
            record.setdefault("extensions", {})["clinical_impressions"] = clinical_impressions
        else:
            record.documents = documents
            ext = _o(record, "extensions", None)
            if ext is None:
                record.extensions = {}
                ext = record.extensions
            ext["clinical_impressions"] = clinical_impressions
