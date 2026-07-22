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

Supported generation_frequency values (α-min-2, extended in α-min-3):
  admission_once  → 1 document at day 0 (inpatient H&P, nursing assessment)
  admission_once_if_rehab_sessions → 1 document at the first RehabSession's
                    date, only if the encounter has ≥1 RehabSession record
                    (chain 2: rehabilitation_plan, MHLW 別紙様式21)
  daily           → 1 document per LOS day (progress note)
  daily_3shift    → 3 documents per LOS day at night 00:00 / day 08:00 /
                    evening 16:00 (nursing shift note, α-min-3); mirrors
                    `daily` skip rules (LOS=1 skip, AD-32 in-progress proxy)
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
from datetime import datetime, time, timedelta
from functools import lru_cache
from typing import Any

from clinosim.modules._shared import get_attr_or_key as _o
from clinosim.modules._shared import resolve_lang
from clinosim.modules.document import (
    CLINICAL_IMPRESSION_ID_PREFIX,
    DOC_REFERENCE_ID_PREFIX,
    specs_for_country,
    specs_for_encounter_type,
)
from clinosim.types.clinical import ClinicalDocument, ClinicalImpressionRecord
from clinosim.types.document import DocumentType

logger = logging.getLogger(__name__)

# AD-65 Bug B: nursing-authored document types (LOINC codes) — DERIVED FROM
# document_type_specs.yaml (F-7 adv-1 fix). Pre-fix this was a hardcoded
# frozenset({"34746-8", "78390-2", "34745-0"}) that duplicated the YAML
# values, so a future LOINC swap in the YAML would silently leave the
# author-dispatch gate reading stale codes (single-edit-point rule).
# clinosim/codes/data/loinc.yaml 78390-2 comment documents the rationale
# for those specific codes (34119-8 was rejected as SNF, not hospital).
_NURSING_DOC_TYPE_KEYS = frozenset(
    {
        "admission_nursing_assessment",
        "nursing_shift_note",
        "nursing_discharge_summary",
    }
)


@lru_cache(maxsize=1)
def _load_nursing_loincs() -> frozenset[str]:
    """Derive the nursing LOINC set from document_type_specs.yaml at import time.

    Late-bound (lru_cache) to avoid circular import: `document/__init__.py`
    imports NURSING_LOINCS from this module, and `load_document_type_specs`
    reads a YAML that gets its schema from the same __init__ package. The
    cache means one YAML round-trip per process.
    """
    from clinosim.modules.document.narrative.registry import load_document_type_specs

    specs = load_document_type_specs()
    result = frozenset(specs[DocumentType(k)].loinc_code for k in _NURSING_DOC_TYPE_KEYS)
    assert len(result) == 3, f"expected 3 distinct nursing LOINCs from document_type_specs.yaml, got {sorted(result)}"
    return result


NURSING_LOINCS = _load_nursing_loincs()

# Encounter types that receive daily ClinicalImpressionRecords (spec §3.3).
# CI is a "daily working diagnosis update" — only meaningful for multi-day inpatient stays.
# Outpatient / Emergency encounters do NOT receive ClinicalImpression entries.
_CI_ENCOUNTER_TYPES: frozenset[str] = frozenset(
    {
        "inpatient",
        "icu",
        "rehab_inpatient",
    }
)

_CANCELLED_STATUSES: frozenset[str] = frozenset({"cancelled"})

# α-min-3: acute-care nursing 3-shift schedule for `daily_3shift` specs.
# Writer-owned canonical constant (single edit point — sibling to
# DOC_REFERENCE_ID_PREFIX ownership). Neutral shift keys are stored in
# structural CIF (`ClinicalDocument.shift`); localized labels (JP 深夜/日勤/
# 準夜) are resolved at Stage 2 render time by language (AD-30 spirit).
# Order is chronological within the calendar day so authored_datetime is
# monotonic with document sequence: night 00:00-08:00 / day 08:00-16:00 /
# evening 16:00-24:00.
SHIFT_SCHEDULE: tuple[tuple[str, int], ...] = (
    ("night", 0),
    ("day", 8),
    ("evening", 16),
)


# P2-13 PR2b (session 47): JP-CLINS 診療情報提供書 emission rate.
# 0.20 = 20% of eligible inpatient discharges emit a referral note.
# Empirical acute-care hospital benchmark from spec §3.2.2. Deterministic
# per (encounter_id, patient_id) so the same cohort seed produces the same
# subset of referral-note emitters — no new RNG allocation needed.
REFERRAL_NOTE_FIRE_RATE = 0.20


def _referral_note_fires(encounter_id: str, patient_id: str) -> bool:
    """Return True if this encounter should emit a JP-CLINS referral note.

    Deterministic:
      hash((encounter_id, patient_id)) as an int → normalized to [0, 1).
      Fires when the value is below REFERRAL_NOTE_FIRE_RATE. The hash is
      hashlib.sha256-based (like session 46 P1-7 lot_number fix) so the
      result is stable across Python invocations and locales.
    """
    import hashlib

    key = f"{encounter_id}::{patient_id}".encode()
    digest = hashlib.sha256(key).digest()
    frac = int.from_bytes(digest[:8], "big") / (1 << 64)
    return frac < REFERRAL_NOTE_FIRE_RATE


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


def _make_doc_stub(
    spec: Any,
    encounter_id: str,
    doc_seq: int,
    dt: datetime,
    pid: str,
    lang: str,
    author: str,
) -> ClinicalDocument:
    """Shared ClinicalDocument construction for the admission_once family of
    generation_frequency branches (admission_once / admission_once_los_gt_7 /
    admission_once_if_rehab_sessions) — all three set authored_datetime ==
    period_start == period_end to the same instant `dt`. Extracted once a
    third variant landed (rehabilitation_plan design spec §3b), closing the
    nutrition_care_plan chain's PR #139 deferred TODO ("LOS-gated
    document_enricher pattern") — mechanical refactor, no behavior change to
    the two existing call sites (admission_dt in, identical ClinicalDocument
    out).
    """
    return ClinicalDocument(
        document_id=f"{DOC_REFERENCE_ID_PREFIX}{encounter_id}-{doc_seq:02d}",
        task_type=spec.type_key,
        loinc_code=spec.loinc_code,
        patient_id=pid,
        encounter_id=encounter_id,
        author_practitioner_id=author,
        authored_datetime=dt.isoformat(),
        period_start=dt.isoformat(),
        period_end=dt.isoformat(),
        language=lang,
        format_type=spec.format_type.value,
        narrative=None,
    )


# ---------------------------------------------------------------------------
# Enricher entry point
# ---------------------------------------------------------------------------


def document_enricher(ctx: Any) -> None:
    """POST_ENCOUNTER enricher: emit ClinicalDocument stubs + ClinicalImpressionRecords.

    Per encounter in ctx.records (country × encounter_type intersection applied):
      - admission_once specs  → 1 document at day 0
      - daily specs           → 1 document per LOS day (skipped for LOS=1; spec §7)
      - daily_3shift specs    → 3 documents per LOS day (night/day/evening;
                                same LOS=1 skip; α-min-3)
      - discharge_once specs  → 1 document at day LOS-1, skipped if in-progress (AD-32)
      - encounter_once specs  → 1 document at day 0 (outpatient / ED single-visit)
      - ClinicalImpressionRecord → 1 per LOS day (inpatient/icu/rehab_inpatient only; spec §3.3)

    EnricherContext interface (POST_ENCOUNTER):
      ctx.master_seed  — int
      ctx.records      — list with exactly 1 CIFPatientRecord-like object
      ctx.config       — SimulatorConfig-like; ctx.config.country = "us" | "jp"
    """
    country: str = str(_o(ctx.config, "country", "us") or "us").lower()
    lang = resolve_lang(country)

    # Pre-compute country spec key set once per enricher call (lru_cache hit on repeated calls).
    country_spec_keys: frozenset[str] = frozenset(s.type_key for s in specs_for_country(country))

    for record in ctx.records:
        patient = _o(record, "patient", None)
        pid: str = (_o(patient, "patient_id", "") or "") if patient is not None else ""

        # Start from existing documents (preserves any pre-enricher stubs).
        documents: list[ClinicalDocument] = list(_o(record, "documents", []) or [])

        # Start from existing clinical_impressions (in case enricher is called >1x).
        raw_ext = _o(record, "extensions", {}) or {}
        clinical_impressions: list[ClinicalImpressionRecord] = list(raw_ext.get("clinical_impressions", []))

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
            applicable_specs = [s for s in specs_for_encounter_type(enc_type_val) if s.type_key in country_spec_keys]

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
                    documents.append(
                        _make_doc_stub(
                            spec,
                            encounter_id,
                            doc_seq,
                            admission_dt,
                            pid,
                            lang,
                            _pick_document_author(spec, encounter),
                        )
                    )
                    doc_seq += 1

                elif freq == "admission_once_los_gt_7":
                    # MHLW mandate: 栄養管理計画書 required only for admissions
                    # > 7 days (design spec §3a). Mirrors the `daily` branch's
                    # LOS-skip pattern below.
                    if los_days <= 7:
                        continue
                    documents.append(
                        _make_doc_stub(
                            spec,
                            encounter_id,
                            doc_seq,
                            admission_dt,
                            pid,
                            lang,
                            _pick_document_author(spec, encounter),
                        )
                    )
                    doc_seq += 1

                elif freq == "admission_once_if_rehab_sessions":
                    # MHLW 別紙様式21: rehabilitation plan required only when the
                    # patient is actually receiving disease-specific rehab therapy
                    # (design spec §1 — reuses the existing RehabSession data
                    # rather than the never-fired rehab_inpatient ward-transfer
                    # scaffold). authored_datetime = first rehab session's date,
                    # NOT admission_dt (the plan is assessed when rehab starts,
                    # which is POD1+ per generate_rehab_sessions, not at admission).
                    enc_rehab_sessions = [
                        s for s in (_o(record, "rehab_sessions", []) or []) if _o(s, "encounter_id", "") == encounter_id
                    ]
                    if not enc_rehab_sessions:
                        continue
                    first_session_dt = min(_o(s, "session_date", admission_dt) for s in enc_rehab_sessions)
                    documents.append(
                        _make_doc_stub(
                            spec,
                            encounter_id,
                            doc_seq,
                            first_session_dt,
                            pid,
                            lang,
                            _pick_document_author(spec, encounter),
                        )
                    )
                    doc_seq += 1

                elif freq == "daily":
                    # Spec §7: daily notes skipped for LOS<1 encounters
                    # (LOS=0 = day-surgery / immediate discharge、intermediate
                    # notes 不要)。
                    # Issue #337 (session 62):従来 `<= 1` で LOS=1 encounter も
                    # skip していたが、eDS Composition (discharge_once) は
                    # LOS=1 でも emit されるため hospitalCourseSection.entry
                    # min=1 の valid DocumentReference target が欠落 →
                    # v9 で 3 件 slice error 発火。LOS=1 の 1 progress_note は
                    # 「入院当日 = 全入院期間の hospital course summary」
                    # として clinically valid、spec 準拠と両立。
                    # daily_3shift (nursing) は 3-per-day cadence 保持のため
                    # LOS=1 skip を維持(下記)。
                    if los_days < 1:
                        continue
                    for day in range(los_days):
                        day_dt = admission_dt + timedelta(days=day)
                        documents.append(
                            ClinicalDocument(
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
                            )
                        )
                        doc_seq += 1

                elif freq == "daily_3shift":
                    # α-min-3: 3 notes per LOS day (night 00:00 / day 08:00 /
                    # evening 16:00). Mirrors the `daily` branch: skipped for
                    # LOS=1 same-day encounters (spec §7), and in-progress
                    # encounters (AD-32) use the same los_days proxy — partial
                    # data up to the snapshot day only.
                    if los_days <= 1:
                        continue
                    for day in range(los_days):
                        day_date = (admission_dt + timedelta(days=day)).date()
                        for shift_key, shift_hour in SHIFT_SCHEDULE:
                            shift_dt = datetime.combine(day_date, time(hour=shift_hour))
                            documents.append(
                                ClinicalDocument(
                                    document_id=(f"{DOC_REFERENCE_ID_PREFIX}{encounter_id}-{doc_seq:02d}-{shift_key}"),
                                    task_type=spec.type_key,
                                    loinc_code=spec.loinc_code,
                                    patient_id=pid,
                                    encounter_id=encounter_id,
                                    author_practitioner_id=_pick_document_author(spec, encounter),
                                    authored_datetime=shift_dt.isoformat(),
                                    period_start=shift_dt.isoformat(),
                                    period_end=shift_dt.isoformat(),
                                    language=lang,
                                    format_type=spec.format_type.value,
                                    shift=shift_key,
                                    narrative=None,
                                )
                            )
                            doc_seq += 1

                elif freq == "discharge_once":
                    if is_in_progress:
                        continue  # AD-32: no discharge summary while encounter is open
                    end_dt = discharge_dt or admission_dt  # discharge_dt is non-None here
                    documents.append(
                        ClinicalDocument(
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
                        )
                    )
                    doc_seq += 1

                elif freq == "discharge_fraction_20pct":
                    # P2-13 PR2b (session 47): JP-CLINS 診療情報提供書 fires on
                    # a deterministic 20% subset of inpatient discharges
                    # (empirical acute-care hospital referral-note rate).
                    # AD-32: no referral note while encounter is open.
                    # AD-16: per-record deterministic RNG (encounter_id +
                    # patient_id as the discriminator; no new sub-seed
                    # allocation needed — the seed is stable string hashing).
                    if is_in_progress:
                        continue
                    if not _referral_note_fires(encounter_id, pid):
                        continue
                    end_dt = discharge_dt or admission_dt
                    documents.append(
                        ClinicalDocument(
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
                        )
                    )
                    doc_seq += 1

                elif freq == "checkup_once":
                    # P2-13 PR3(session 47):JP-eCheckup 健診結果報告書
                    # opt-in。config.module_enabled("health_checkup") が
                    # True の場合のみ発行対象。encounter_types_supported
                    # ["checkup"] gate と併せて、通常の inpatient/outpatient
                    # encounter には絶対に発火しない設計。
                    if not ctx.config.module_enabled("health_checkup"):
                        continue
                    end_dt = discharge_dt or admission_dt
                    documents.append(
                        ClinicalDocument(
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
                        )
                    )
                    doc_seq += 1

                elif freq == "encounter_once":
                    # Single-visit encounters (outpatient SOAP, ED note, ED triage note).
                    # Emit at day 0; period covers full encounter duration.
                    # AD-32: if discharge_dt is None (rare in-progress outpatient/ED),
                    # still emit — single-visit context makes partial data meaningful.
                    end_dt = discharge_dt or admission_dt
                    documents.append(
                        ClinicalDocument(
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
                        )
                    )
                    doc_seq += 1

            # ── ClinicalImpression generation (inpatient types only; spec §3.3) ─
            if emit_ci:
                # C4-11 (session 43 cycle 4): richer template description.
                # Pre-fix was a 25-char stub ("Day N clinical assessment").
                # Now includes disease id + severity + phase hint. Purely
                # template-driven (deterministic, no LLM) — β-JP-1 is a
                # DocumentReference/Composition narrative pass and does not
                # touch ClinicalImpression.description.
                _disease_id = _o(encounter, "disease_id", "") or ""
                _severity = _o(encounter, "severity", "") or ""
                _enc_label = (
                    "inpatient"
                    if enc_type_val == "inpatient"
                    else ("ICU" if "icu" in enc_type_val.lower() else "rehab")
                )
                # Issue #360 G4: JP-localized encounter labels + phase hints for
                # ClinicalImpression.description_ja. Parallel to the English template
                # already computed below; consumed by _build_clinical_impression on
                # JP output (AD-30: CIF stores both because ClinicalImpressionRecord
                # has no diagnosis/severity code — the JP description cannot be
                # re-derived from a code_lookup at FHIR emission time).
                _enc_label_ja = (
                    "入院"
                    if enc_type_val == "inpatient"
                    else ("ICU" if "icu" in enc_type_val.lower() else "リハビリ入院")
                )
                for day in range(los_days):
                    day_dt = admission_dt + timedelta(days=day)
                    # AD-32: the last day of an in-progress encounter is "in-progress"
                    # (encounter still open; prior days remain "completed").
                    last_day_of_in_progress = is_in_progress and (day == los_days - 1)
                    # Phase hint (deterministic by day-index vs LOS).
                    if los_days <= 2:
                        _phase = "brief admission"
                        _phase_ja = "短期入院"
                    elif day == 0:
                        _phase = "admission workup"
                        _phase_ja = "入院時精査"
                    elif day == los_days - 1:
                        _phase = "pre-discharge review"
                        _phase_ja = "退院前評価"
                    elif day < los_days / 3:
                        _phase = "acute phase"
                        _phase_ja = "急性期"
                    elif day < 2 * los_days / 3:
                        _phase = "stabilisation"
                        _phase_ja = "安定期"
                    else:
                        _phase = "recovery"
                        _phase_ja = "回復期"
                    _dx_part = f" for {_disease_id}" if _disease_id else ""
                    _sev_part = f" ({_severity})" if _severity else ""
                    description = (
                        f"Day {day + 1} of {los_days} {_enc_label} clinical assessment"
                        f"{_dx_part}{_sev_part} — {_phase}. Attending review of vitals, "
                        f"medication response, complication risk, and progress toward "
                        f"discharge criteria."
                    )
                    # JP description — 主治医が JP-CLINS Progress Note / ClinicalImpression
                    # を読む画面で表示される。iris4h-ai 2026-07-22 feedback G4。
                    _dx_part_ja = f"（{_disease_id}）" if _disease_id else ""
                    _sev_part_ja = f"（{_severity}）" if _severity else ""
                    description_ja = (
                        f"{_enc_label_ja}第{day + 1}病日／全{los_days}病日 臨床評価"
                        f"{_dx_part_ja}{_sev_part_ja} — {_phase_ja}。"
                        f"バイタル・薬効反応・合併症リスク・退院基準への進捗を主治医が評価。"
                    )
                    clinical_impressions.append(
                        ClinicalImpressionRecord(
                            impression_id=f"{CLINICAL_IMPRESSION_ID_PREFIX}{encounter_id}-{day}",
                            encounter_id=encounter_id,
                            date=day_dt.date(),
                            day_index=day,
                            description=description,
                            description_ja=description_ja,
                            practitioner_id=attending_id,
                            is_in_progress=last_day_of_in_progress,
                        )
                    )

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
