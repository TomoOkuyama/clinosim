"""Document module POST_ENCOUNTER enricher (Tier 1 #3 α-min-2 Task 10, AD-55).

Generates ClinicalDocument stubs (Stage 1 text via TemplateNarrativeGenerator)
and ClinicalImpressionRecord entries (daily working-diagnosis updates) for each
encounter that has applicable document specs.

Architecture:
- POST_ENCOUNTER order=95 (after imaging=90)
- Always-on Module (enabled=lambda c: True)
- Writes to record.documents (list[ClinicalDocument]) and
  record.extensions["clinical_impressions"] (list[ClinicalImpressionRecord])
- Locale gating via specs_for_country(country) — only applicable specs emitted
- Encounter-type gating via specs_for_encounter_type(enc_type) — per-spec allowlist
  (DocumentTypeSpec.encounter_types_supported); α-min-1 specs declare [inpatient,
  icu, rehab_inpatient]; α-min-2 outpatient/ED specs declare their own allowlists
- All field reads via _o() for dict/dataclass dual access (silent-no-op defense)
- DOC_REFERENCE_ID_PREFIX + CLINICAL_IMPRESSION_ID_PREFIX from __init__.py
  are the writer-owned canonical constants (reader Task 9 imports from here)

Supported generation_frequency values (α-min-2):
  admission_once  → 1 document at day 0 (inpatient H&P, nursing assessment)
  daily           → 1 document per LOS day (progress note, nursing shift)
  discharge_once  → 1 document at final day, skipped if in-progress (AD-32)
  encounter_once  → 1 document at day 0 for outpatient/ED encounters

ClinicalImpression gating (spec §3.3):
  INPATIENT / ICU / REHAB_INPATIENT → ClinicalImpressionRecord daily (unchanged).
  OUTPATIENT / EMERGENCY / other types → NO ClinicalImpression
  (CI is "daily working diagnosis update"; not applicable for single-visit encounters).

AD-32 snapshot compliance:
  DISCHARGE_SUMMARY (generation_frequency="discharge_once") is skipped when
  encounter.discharge_datetime is None (in-progress / snapshot truncation).
  For encounter_once specs (outpatient/ED) with discharge_datetime=None, the
  document is emitted anyway (single-visit context; AD-32 in-progress is rare).

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
    specs_for_encounter_type,
)
from clinosim.modules.document.narrative.context import build_narrative_context
from clinosim.modules.document.narrative.llm_generator import LLMNarrativeGenerator
from clinosim.types.clinical import ClinicalDocument, ClinicalImpressionRecord
from clinosim.types.document import DocumentType

# Encounter types that receive daily ClinicalImpressionRecords (spec §3.3).
# CI is a "daily working diagnosis update" — only meaningful for multi-day inpatient stays.
# Outpatient / Emergency encounters do NOT receive ClinicalImpression entries.
_CI_ENCOUNTER_TYPES: frozenset[str] = frozenset({
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


# ---------------------------------------------------------------------------
# Enricher entry point
# ---------------------------------------------------------------------------


def document_enricher(ctx: Any) -> None:
    """POST_ENCOUNTER enricher: emit ClinicalDocument stubs + ClinicalImpressionRecords.

    Per encounter in ctx.records (country × encounter_type intersection applied):
      - admission_once specs  → 1 document at day 0
      - daily specs           → 1 document per LOS day (skipped for LOS=1; spec §7)
      - discharge_once specs  → 1 document at day LOS-1, skipped if in-progress (AD-32)
      - encounter_once specs  → 1 document at day 0 (outpatient / ED single-visit)
      - ClinicalImpressionRecord → 1 per LOS day (inpatient/icu/rehab_inpatient only; spec §3.3)

    EnricherContext interface (POST_ENCOUNTER):
      ctx.master_seed  — int
      ctx.records      — list with exactly 1 CIFPatientRecord-like object
      ctx.config       — SimulatorConfig-like; ctx.config.country = "us" | "jp"
    """
    country: str = str(_o(ctx.config, "country", "us") or "us").lower()
    lang = "ja" if country == "jp" else "en"
    generator = LLMNarrativeGenerator()

    # Pre-compute country spec key set once per enricher call (lru_cache hit on repeated calls).
    country_spec_keys: frozenset[str] = frozenset(
        s.type_key for s in specs_for_country(country)
    )

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

            enc_status_val = _enc_status_value(_o(encounter, "status", None))
            if enc_status_val in _CANCELLED_STATUSES:
                continue  # AD-32: cancelled encounters produce no documents

            # Per-spec encounter-type × country intersection.
            # specs_for_encounter_type is lru_cache(maxsize=4); cheap repeated call.
            applicable_specs = [
                s for s in specs_for_encounter_type(enc_type_val)
                if s.type_key in country_spec_keys
            ]

            emit_ci = enc_type_val in _CI_ENCOUNTER_TYPES

            if not applicable_specs and not emit_ci:
                continue  # unknown encounter type or no specs + no CI → skip

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

            # ── Document generation (per applicable spec) ────────────────────
            for spec in applicable_specs:
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
                        # TODO(Task 3): removed in AD-65 — _narrative_to_text deleted;
                        # this branch is refactored in Task 3 to populate
                        # ClinicalDocument.narrative (stub-only here) instead of text=.
                        text_source=output.metadata.get("generator", "template"),
                        sections=dict(output.sections),
                        format_type=spec.format_type.value,
                    ))
                    doc_seq += 1

                elif freq == "daily":
                    # Spec §7: daily notes skipped for LOS=1 same-day encounters.
                    # A same-day admission/discharge has an H&P and discharge summary;
                    # intermediate notes are clinically redundant.
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
                            # TODO(Task 3): removed in AD-65 — _narrative_to_text deleted;
                            # this branch is refactored in Task 3 to populate
                            # ClinicalDocument.narrative (stub-only here) instead of text=.
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
                        # TODO(Task 3): removed in AD-65 — _narrative_to_text deleted;
                        # this branch is refactored in Task 3 to populate
                        # ClinicalDocument.narrative (stub-only here) instead of text=.
                        text_source=output.metadata.get("generator", "template"),
                        sections=dict(output.sections),
                        format_type=spec.format_type.value,
                    ))
                    doc_seq += 1

                elif freq == "encounter_once":
                    # Single-visit encounters (outpatient SOAP, ED note, ED triage note).
                    # Emit at day 0; period covers full encounter duration.
                    # AD-32: if discharge_dt is None (rare in-progress outpatient/ED),
                    # still emit — single-visit context makes partial data meaningful.
                    end_dt = discharge_dt or admission_dt
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
                        period_end=end_dt.isoformat(),
                        language=lang,
                        # TODO(Task 3): removed in AD-65 — _narrative_to_text deleted;
                        # this branch is refactored in Task 3 to populate
                        # ClinicalDocument.narrative (stub-only here) instead of text=.
                        text_source=output.metadata.get("generator", "template"),
                        sections=dict(output.sections),
                        format_type=spec.format_type.value,
                    ))
                    doc_seq += 1

            # ── ClinicalImpression generation (inpatient types only; spec §3.3) ─
            if emit_ci:
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
