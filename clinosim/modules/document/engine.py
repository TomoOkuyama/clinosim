"""Document module POST_ENCOUNTER enricher (Tier 1 #3 α-min-2 Task 10, AD-55;
refactored to stub-only in AD-65 Task 3).

Generates ClinicalDocument STRUCTURAL STUBS (narrative=None) and
ClinicalImpressionRecord entries (daily working-diagnosis updates) for each
encounter that has applicable document specs. Narrative text generation is
NOT performed here — see the "Two-pass lifecycle" note below.

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

Two-pass lifecycle (AD-65):
  Pass 1 (this module): emits STRUCTURAL STUBS ONLY — ClinicalDocument with
  narrative=None. No text/sections population happens here.
  Pass 2 (clinosim/modules/document/narrative/passes.py — TemplateNarrativePass,
  future LLMNarrativePass): a separate Stage 2 pass reads the written
  structural CIF, builds NarrativeContext per stub, runs the generator, and
  writes cif/narratives/<version>/documents/<enc>/<doc_type>.json. CIFReader
  merges structural + narrative trees before FHIR emit.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from clinosim.modules._shared import get_attr_or_key as _o
from clinosim.modules.document import (
    CLINICAL_IMPRESSION_ID_PREFIX,
    DOC_REFERENCE_ID_PREFIX,
    specs_for_country,
    specs_for_encounter_type,
)
from clinosim.types.clinical import ClinicalDocument, ClinicalImpressionRecord

logger = logging.getLogger(__name__)

# AD-65 Bug B: nursing-authored document types (LOINC codes).
# 78390-2 = admission_nursing_assessment, 34746-8 = nursing_shift_note,
# 34745-0 = nursing_discharge_summary (document_type_specs.yaml is the
# authoritative source; clinosim/codes/data/loinc.yaml 78390-2 comment
# documents that 34119-8 — used in early Task-8 drafts of this task — was
# REJECTED as the wrong code, "Nursing facility Initial evaluation note"
# (SNF, not hospital); using it here would silently leave
# nursing_discharge_summary author unfixed, exactly the class of bug this
# task exists to close).
# Used by _pick_document_author to dispatch author_practitioner_id to
# encounter.primary_nurse_id instead of encounter.attending_physician_id.
NURSING_LOINCS = frozenset({"34746-8", "78390-2", "34745-0"})

# Encounter types that receive daily ClinicalImpressionRecords (spec §3.3).
# CI is a "daily working diagnosis update" — only meaningful for multi-day inpatient stays.
# Outpatient / Emergency encounters do NOT receive ClinicalImpression entries.
_CI_ENCOUNTER_TYPES: frozenset[str] = frozenset({
    "inpatient",
    "icu",
    "rehab_inpatient",
})

_CANCELLED_STATUSES: frozenset[str] = frozenset({"cancelled"})


def _pick_document_author(spec: Any, encounter: Any) -> str:
    """AD-65 Bug B fix: author dispatch by document type.

    Session 27 clinical-integrity review found 23,279 nursing docs (LOINC
    34746-8 / 78390-2 / 34745-0) had ``author_practitioner_id`` set to the
    attending physician instead of the assigned nurse — clinically incorrect
    (a nursing assessment/shift note/discharge summary is authored by
    nursing staff, not the physician of record).

    Nursing docs (``spec.loinc_code`` in `NURSING_LOINCS`) → ``encounter.primary_nurse_id``.
    All other (physician) docs → ``encounter.attending_physician_id`` (unchanged behavior).
    Fallback: if a nursing doc's encounter has no assigned nurse (e.g. the
    nursing_assignment enricher didn't fire), fall back to the attending and
    log a warning — this should be rare and worth investigating if seen at
    volume, but must not raise (blank author is worse than a physician author).
    """
    loinc = _o(spec, "loinc_code", "")
    if loinc in NURSING_LOINCS:
        nurse = _o(encounter, "primary_nurse_id", "") or ""
        if nurse:
            return nurse
        logger.warning(
            "nursing doc %s falling back to attending (primary_nurse_id missing)",
            loinc,
        )
    return _o(encounter, "attending_physician_id", "") or ""


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

            # ── Document generation (per applicable spec) ────────────────────
            # AD-65 two-pass architecture: this enricher creates STRUCTURAL STUBS
            # only (narrative=None). Narrative text/sections population moved to
            # TemplateNarrativePass (clinosim/modules/document/narrative/passes.py),
            # which runs as a separate Stage 2 pass over the written structural CIF.
            for spec in applicable_specs:
                freq = spec.generation_frequency

                if freq == "admission_once":
                    documents.append(ClinicalDocument(
                        document_id=f"{DOC_REFERENCE_ID_PREFIX}{encounter_id}-{doc_seq:02d}",
                        task_type=spec.type_key,
                        loinc_code=spec.loinc_code,
                        patient_id=pid,
                        encounter_id=encounter_id,
                        author_practitioner_id=_pick_document_author(spec, encounter),
                        authored_datetime=admission_dt.isoformat(),
                        period_start=admission_dt.isoformat(),
                        period_end=admission_dt.isoformat(),
                        language=lang,
                        format_type=spec.format_type.value,
                        narrative=None,
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
                        documents.append(ClinicalDocument(
                            document_id=f"{DOC_REFERENCE_ID_PREFIX}{encounter_id}-{doc_seq:02d}",
                            task_type=spec.type_key,
                            loinc_code=spec.loinc_code,
                            patient_id=pid,
                            encounter_id=encounter_id,
                            author_practitioner_id=_pick_document_author(spec, encounter),
                            authored_datetime=day_dt.isoformat(),
                            period_start=day_dt.isoformat(),
                            period_end=day_dt.isoformat(),
                            language=lang,
                            format_type=spec.format_type.value,
                            narrative=None,
                        ))
                        doc_seq += 1

                elif freq == "discharge_once":
                    if is_in_progress:
                        continue  # AD-32: no discharge summary while encounter is open
                    end_dt = discharge_dt or admission_dt  # discharge_dt is non-None here
                    documents.append(ClinicalDocument(
                        document_id=f"{DOC_REFERENCE_ID_PREFIX}{encounter_id}-{doc_seq:02d}",
                        task_type=spec.type_key,
                        loinc_code=spec.loinc_code,
                        patient_id=pid,
                        encounter_id=encounter_id,
                        author_practitioner_id=_pick_document_author(spec, encounter),
                        authored_datetime=end_dt.isoformat(),
                        period_start=admission_dt.isoformat(),
                        period_end=end_dt.isoformat(),
                        language=lang,
                        format_type=spec.format_type.value,
                        narrative=None,
                    ))
                    doc_seq += 1

                elif freq == "encounter_once":
                    # Single-visit encounters (outpatient SOAP, ED note, ED triage note).
                    # Emit at day 0; period covers full encounter duration.
                    # AD-32: if discharge_dt is None (rare in-progress outpatient/ED),
                    # still emit — single-visit context makes partial data meaningful.
                    end_dt = discharge_dt or admission_dt
                    documents.append(ClinicalDocument(
                        document_id=f"{DOC_REFERENCE_ID_PREFIX}{encounter_id}-{doc_seq:02d}",
                        task_type=spec.type_key,
                        loinc_code=spec.loinc_code,
                        patient_id=pid,
                        encounter_id=encounter_id,
                        author_practitioner_id=_pick_document_author(spec, encounter),
                        authored_datetime=admission_dt.isoformat(),
                        period_start=admission_dt.isoformat(),
                        period_end=end_dt.isoformat(),
                        language=lang,
                        format_type=spec.format_type.value,
                        narrative=None,
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
