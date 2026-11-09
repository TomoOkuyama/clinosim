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
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from functools import lru_cache
from typing import Any

from clinosim.codes.loinc import loinc_display
from clinosim.codes.snomed_concepts import SURGICAL_PROCEDURE
from clinosim.countries import lang_for
from clinosim.locale.i18n import t
from clinosim.modules._shared import get_attr_or_key as _o
from clinosim.modules.document import (
    CLINICAL_IMPRESSION_ID_PREFIX,
    DOC_REFERENCE_ID_PREFIX,
    specs_for_country,
    specs_for_encounter_type,
)
from clinosim.modules.document.narrative._narrative_utils import encounter_died
from clinosim.modules.document.narrative.registry import document_loinc
from clinosim.types.clinical import ClinicalDocument, ClinicalImpressionRecord
from clinosim.types.document import DocumentType

logger = logging.getLogger(__name__)

# AD-65 Bug B: nursing-authored document types (LOINC codes) — DERIVED FROM
# document_type_specs.yaml (F-7 adv-1 fix). Pre-fix this was a hardcoded
# frozenset of the three nursing LOINC codes that duplicated the YAML
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


def _severity_label(severity: str, lang: str) -> str:
    """The encounter severity in ``lang`` (Issue #3032): 軽症 / 中等症 / 重症."""
    from clinosim.locale.loader import narrative_label

    return narrative_label("encounter_severity", str(severity).strip().lower(), lang, fallback=str(severity))


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

# Issue #957: LOINC code substituted for OUTPATIENT_SOAP on oncology
# service-line encounters (e.g. chemo_visit). 34133-9 "Summary of episode
# note" is the generic episode-summary LOINC — a more descriptive fit
# for a chemo cycle visit than the routine outpatient SOAP note code
# 34131-3. The spec.loinc_code remains 34131-3 as the default; this
# override only fires when `encounter.service_line == "oncology"`.
_ONCOLOGY_OUTPATIENT_SOAP_LOINC: str = "34133-9"


def _effective_outpatient_loinc(spec_loinc: str, encounter: Any) -> str:
    """Return the effective LOINC for an ``encounter_once`` outpatient
    document, substituting the oncology-service-line code on
    OUTPATIENT_SOAP when applicable (Issue #957).

    Returns ``spec_loinc`` unchanged for every other case (non-oncology
    service line, non-OUTPATIENT_SOAP spec, or when ``encounter`` has no
    ``service_line`` attribute — backwards-compat with older CIF).
    """
    if spec_loinc != document_loinc("outpatient_soap"):
        return spec_loinc
    if _o(encounter, "service_line", "") == "oncology":
        return _ONCOLOGY_OUTPATIENT_SOAP_LOINC
    return spec_loinc


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
SHIFT_HOURS = 8  # length of each shift in SHIFT_SCHEDULE (Issue #2651: MAR window)


# P2-13 PR2b: JP-CLINS 診療情報提供書 emission rate.
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
      hashlib.sha256-based (like P1-7 lot_number fix) so the
      result is stable across Python invocations and locales.
    """
    from clinosim.determinism import sha_bernoulli

    return sha_bernoulli(f"{encounter_id}::{patient_id}", REFERRAL_NOTE_FIRE_RATE)


def _pick_document_author(spec: Any, encounter: Any) -> str:
    """AD-65 Bug B fix: author dispatch by document type.

    clinical-integrity review found 23,279 nursing docs (LOINC
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
# Document planners (Issue #2532)
# ---------------------------------------------------------------------------
#
# Each ``generation_frequency`` value maps to a planner that decides which
# documents an encounter gets and when they are dated; one builder turns the
# plans into ``ClinicalDocument`` stubs with sequential ids. The planner keys
# must equal ``narrative.registry.GENERATION_FREQUENCIES`` (the YAML-load
# allowlist; a unit test pins the two together).


@dataclass(frozen=True)
class _EncounterFacts:
    """What the planners read about one encounter."""

    record: Any
    encounter: Any
    encounter_id: str
    pid: str
    admission_dt: datetime
    discharge_dt: datetime | None
    los_days: int
    config: Any

    @property
    def is_in_progress(self) -> bool:
        return self.discharge_dt is None

    @property
    def end_dt(self) -> datetime:
        return self.discharge_dt or self.admission_dt


@dataclass(frozen=True)
class _DocPlan:
    """One planned document: its timing, document-id suffix and the fields
    that differ from the spec defaults. ``author`` None means the default
    author for the spec (``_pick_document_author``)."""

    authored: str
    period_start: str
    period_end: str
    id_suffix: str = ""
    author: str | None = None
    loinc_code: str | None = None
    shift: str = ""
    related_procedure_id: str = ""


def _point(dt: datetime, **kw: Any) -> _DocPlan:
    """A document dated at one instant (authored == period start == end)."""
    iso = dt.isoformat()
    return _DocPlan(iso, iso, iso, **kw)


def _whole_stay(f: _EncounterFacts) -> _DocPlan:
    """A document authored at discharge covering the whole stay."""
    return _DocPlan(f.end_dt.isoformat(), f.admission_dt.isoformat(), f.end_dt.isoformat())


def _iso(value: Any) -> str:
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def _plan_admission_once(spec: Any, f: _EncounterFacts) -> list[_DocPlan]:
    return [_point(f.admission_dt)]


def _plan_admission_once_los_gt_7(spec: Any, f: _EncounterFacts) -> list[_DocPlan]:
    # MHLW mandate: 栄養管理計画書 required only for admissions > 7 days
    # (design spec §3a).
    return [_point(f.admission_dt)] if f.los_days > 7 else []


def _plan_admission_once_if_rehab_sessions(spec: Any, f: _EncounterFacts) -> list[_DocPlan]:
    # MHLW 別紙様式21: rehabilitation plan required only when the patient is
    # actually receiving disease-specific rehab therapy (design spec §1).
    # Dated at the first rehab session, not admission (the plan is assessed
    # when rehab starts, POD1+ per generate_rehab_sessions).
    sessions = [s for s in (_o(f.record, "rehab_sessions", []) or []) if _o(s, "encounter_id", "") == f.encounter_id]
    if not sessions:
        return []
    return [_point(min(_o(s, "session_date", f.admission_dt) for s in sessions))]


def _plan_daily(spec: Any, f: _EncounterFacts) -> list[_DocPlan]:
    # Spec §7: daily notes skipped for LOS<1 encounters (day surgery /
    # immediate discharge). Issue #337: LOS=1 keeps its one progress note —
    # the eDS Composition (discharge_once) needs a hospitalCourseSection
    # entry target even for one-day stays.
    return [_point(f.admission_dt + timedelta(days=day)) for day in range(f.los_days)]


def _plan_daily_3shift(spec: Any, f: _EncounterFacts) -> list[_DocPlan]:
    # α-min-3: 3 nursing notes per LOS day (night 00:00 / day 08:00 / evening
    # 16:00); skipped for LOS=1 same-day encounters (spec §7). In-progress
    # encounters (AD-32) use the same los_days proxy.
    if f.los_days <= 1:
        return []
    plans = []
    for day in range(f.los_days):
        day_date = (f.admission_dt + timedelta(days=day)).date()
        for shift_key, shift_hour in SHIFT_SCHEDULE:
            shift_dt = datetime.combine(day_date, time(hour=shift_hour))
            # Issue #820 (N-6): no shift record before the patient arrived.
            if shift_dt < f.admission_dt:
                continue
            plans.append(_point(shift_dt, id_suffix=f"-{shift_key}", shift=shift_key))
    return plans


def _plan_discharge_once(spec: Any, f: _EncounterFacts) -> list[_DocPlan]:
    # AD-32: no discharge document while the encounter is open.
    return [] if f.is_in_progress else [_whole_stay(f)]


def _died(f: _EncounterFacts) -> bool:
    return encounter_died(f.encounter)


def _plan_discharge_once_if_alive(spec: Any, f: _EncounterFacts) -> list[_DocPlan]:
    # Issue #961: generic 退院時サマリー for living discharges only; a death
    # gets the 死亡退院サマリー (discharge_once_if_deceased_replaces).
    return [] if f.is_in_progress or _died(f) else [_whole_stay(f)]


def _plan_discharge_once_if_deceased(spec: Any, f: _EncounterFacts) -> list[_DocPlan]:
    # Issue #961: 死亡診断書 (and, under the ``_replaces`` key, the 死亡退院
    # サマリー) for an encounter that ended in death. The certificate is a
    # separate legal document (医師法第 20 条), alongside the summary. AD-32:
    # no death can be certified while the encounter is open.
    return [_whole_stay(f)] if not f.is_in_progress and _died(f) else []


def _plan_discharge_fraction_20pct(spec: Any, f: _EncounterFacts) -> list[_DocPlan]:
    # P2-13 PR2b: JP-CLINS 診療情報提供書 on a deterministic 20% of discharges
    # (AD-16: stable string hashing, no sub-seed).
    if f.is_in_progress or not _referral_note_fires(f.encounter_id, f.pid):
        return []
    return [_whole_stay(f)]


def _plan_checkup_once(spec: Any, f: _EncounterFacts) -> list[_DocPlan]:
    # P2-13 PR3: JP-eCheckup 健診結果報告書, only with the health_checkup module.
    return [_whole_stay(f)] if f.config.module_enabled("health_checkup") else []


def _plan_per_surgical_encounter(spec: Any, f: _EncounterFacts) -> list[_DocPlan]:
    # Issue #991: 手術記録 once per encounter with a surgical ProcedureRecord,
    # for its earliest surgery, authored when the operation ends. Bedside /
    # diagnostic procedures get a procedure_note instead. AD-32: none while
    # the encounter is open.
    if f.is_in_progress:
        return []
    surgical = [
        p
        for p in (_o(f.record, "procedures", []) or [])
        if _o(p, "encounter_id", "") == f.encounter_id and str(_o(p, "category_code", "") or "") == SURGICAL_PROCEDURE
    ]
    if not surgical:
        return []
    primary = min(surgical, key=lambda p: _o(p, "start_datetime", None) or f.admission_dt)
    op_dt = _o(primary, "end_datetime", None) or _o(primary, "start_datetime", None) or f.admission_dt
    return [
        _point(
            op_dt,
            author=_o(primary, "primary_surgeon_id", "") or None,
            related_procedure_id=str(_o(primary, "procedure_id", "") or ""),
        )
    ]


def _plan_per_bedside_procedure(spec: Any, f: _EncounterFacts) -> list[_DocPlan]:
    # Issue #992: one procedure_note per ProcedureRecord whose code is listed
    # under ``procedure_note_codes`` in bedside_procedure_codes.yaml. AD-32: a
    # bedside procedure done today has its note today, open encounter or not.
    from clinosim.modules.document.reference_data_loaders import load_bedside_procedure_codes

    codes = load_bedside_procedure_codes()["procedure_note"]
    plans = []
    for proc in _o(f.record, "procedures", []) or []:
        if _o(proc, "encounter_id", "") != f.encounter_id:
            continue
        if str(_o(proc, "procedure_code", "") or "").strip() not in codes:
            continue
        start = _o(proc, "start_datetime", None) or f.admission_dt
        end = _o(proc, "end_datetime", None) or start
        plans.append(
            _DocPlan(
                _iso(end),
                _iso(start),
                _iso(end),
                id_suffix="-pn",
                author=_o(proc, "primary_surgeon_id", "") or None,
                related_procedure_id=_o(proc, "procedure_id", "") or "",
            )
        )
    return plans


def _plan_encounter_once(spec: Any, f: _EncounterFacts) -> list[_DocPlan]:
    # Single-visit encounters (outpatient SOAP, ED note, ED triage note),
    # authored at arrival and covering the visit; emitted even when open.
    # Issue #957: oncology encounters get LOINC 34133-9.
    return [
        _DocPlan(
            f.admission_dt.isoformat(),
            f.admission_dt.isoformat(),
            f.end_dt.isoformat(),
            loinc_code=_effective_outpatient_loinc(spec.loinc_code, f.encounter),
        )
    ]


_Planner = Callable[[Any, _EncounterFacts], list[_DocPlan]]

_PLANNERS: dict[str, _Planner] = {
    "admission_once": _plan_admission_once,
    "admission_once_los_gt_7": _plan_admission_once_los_gt_7,
    "admission_once_if_rehab_sessions": _plan_admission_once_if_rehab_sessions,
    "daily": _plan_daily,
    "daily_3shift": _plan_daily_3shift,
    "discharge_once": _plan_discharge_once,
    "discharge_once_if_alive": _plan_discharge_once_if_alive,
    "discharge_once_if_deceased": _plan_discharge_once_if_deceased,
    "discharge_once_if_deceased_replaces": _plan_discharge_once_if_deceased,
    "discharge_fraction_20pct": _plan_discharge_fraction_20pct,
    "checkup_once": _plan_checkup_once,
    "per_surgical_encounter": _plan_per_surgical_encounter,
    "per_bedside_procedure": _plan_per_bedside_procedure,
    "encounter_once": _plan_encounter_once,
}


def _build_documents(
    spec: Any,
    plans: list[_DocPlan],
    encounter: Any,
    encounter_id: str,
    pid: str,
    lang: str,
    doc_seq: int,
) -> tuple[list[ClinicalDocument], int]:
    """Stubs (narrative=None; AD-65) for ``plans``, numbered from ``doc_seq``.
    Returns the stubs and the next sequence number."""
    docs = []
    for plan in plans:
        docs.append(
            ClinicalDocument(
                document_id=f"{DOC_REFERENCE_ID_PREFIX}{encounter_id}-{doc_seq:02d}{plan.id_suffix}",
                task_type=spec.type_key,
                loinc_code=plan.loinc_code or spec.loinc_code,
                patient_id=pid,
                encounter_id=encounter_id,
                author_practitioner_id=plan.author or _pick_document_author(spec, encounter),
                related_procedure_id=plan.related_procedure_id,
                authored_datetime=plan.authored,
                period_start=plan.period_start,
                period_end=plan.period_end,
                language=lang,
                format_type=spec.format_type.value,
                shift=plan.shift,
                narrative=None,
            )
        )
        doc_seq += 1
    return docs, doc_seq


def _ed_companion_documents(
    encounter: Any,
    encounter_id: str,
    admission_dt: datetime,
    country_spec_keys: frozenset[str],
    pid: str,
    lang: str,
    doc_seq: int,
) -> tuple[list[ClinicalDocument], int]:
    """Phase B (N-3): ED documents for an inpatient admission that came
    through the ED.

    The FHIR adapter synthesizes a bridge Encounter ``{IMP}-ED`` for a via-ED
    admission (``_make_synth_ed_enc_dict``) so ``Encounter.partOf`` resolves.
    The encounter_once ED specs (救急科記録 34878-9 / トリアージ記録 54094-8)
    target that bridge id so it carries the documents of the ED phase. The
    stubs stay on the IMP record (CY7-05: no new ``record.encounters``
    entry); the narrative pass fills them with the ED templates.
    """
    admit_source = _o(encounter, "admit_source", None)
    if not (str(admit_source) == "emd" or str(admit_source).lower().endswith(".emd")):
        return [], doc_seq
    ed_enc_id = f"{encounter_id}-ED"
    # Mid-ED-window authored time (synth Encounter.period is
    # [admission-3.5h, admission]).
    plan = _DocPlan(
        (admission_dt - timedelta(hours=2)).isoformat(),
        (admission_dt - timedelta(hours=3, minutes=30)).isoformat(),
        admission_dt.isoformat(),
    )
    # Issue #2998: the triage note is written from the ED phase's triage data;
    # without it the note would only read "Triage information: not recorded".
    has_triage = _o(encounter, "triage_data", None) is not None
    docs: list[ClinicalDocument] = []
    for spec in specs_for_encounter_type("emergency"):
        if spec.type_key == DocumentType.ED_TRIAGE_NOTE.value and not has_triage:
            continue
        if spec.type_key in country_spec_keys and spec.generation_frequency == "encounter_once":
            built, doc_seq = _build_documents(spec, [plan], encounter, ed_enc_id, pid, lang, doc_seq)
            docs += built
    return docs, doc_seq


def _clinical_impression_records(
    encounter: Any,
    enc_type_val: str,
    encounter_id: str,
    admission_dt: datetime,
    los_days: int,
    is_in_progress: bool,
    attending_id: str,
    country: str,
) -> list[ClinicalImpressionRecord]:
    """One ClinicalImpressionRecord per LOS day for an inpatient / ICU /
    rehab stay (spec §3.3)."""
    records: list[ClinicalImpressionRecord] = []
    # C4-11: richer template description.
    # Pre-fix was a 25-char stub ("Day N clinical assessment").
    # Now includes disease id + severity + phase hint. Purely
    # template-driven (deterministic, no LLM) — β-JP-1 is a
    # DocumentReference/Composition narrative pass and does not
    # touch ClinicalImpression.description.
    _disease_id = _o(encounter, "disease_id", "") or ""
    _severity = _o(encounter, "severity", "") or ""
    # Labels, phases and descriptions come from the phrase catalog
    # (``narrative_phrases.yaml`` ``clinical_impression``, Issue #2401).
    _enc_key = "inpatient" if enc_type_val == "inpatient" else ("icu" if "icu" in enc_type_val.lower() else "rehab")
    for day in range(los_days):
        day_dt = admission_dt + timedelta(days=day)
        # AD-32: the last day of an in-progress encounter is "in-progress"
        # (encounter still open; prior days remain "completed").
        last_day_of_in_progress = is_in_progress and (day == los_days - 1)
        # Phase hint (deterministic by day-index vs LOS) and the LOINC
        # visit-type code per phase (session-88j P1-12).
        if los_days <= 2:
            _phase_key, _doc_type = "brief_admission", "admission_hp"
        elif day == 0:
            _phase_key, _doc_type = "admission_workup", "admission_hp"
        elif day == los_days - 1:
            _phase_key, _doc_type = "pre_discharge_review", "discharge_summary"
        elif day < los_days / 3:
            _phase_key, _doc_type = "acute_phase", "progress_note"
        elif day < 2 * los_days / 3:
            _phase_key, _doc_type = "stabilisation", "progress_note"
        else:
            _phase_key, _doc_type = "recovery", "progress_note"
        _code_loinc = document_loinc(_doc_type)
        _code_loinc_display = loinc_display(_code_loinc, lang_for(country)) or ""

        def _describe(lang: str) -> str:
            return t(
                "clinical_impression.description",
                lang,
                enc=t(f"clinical_impression.enc_label.{_enc_key}", lang),
                day=day + 1,
                los=los_days,
                dx_part=t("clinical_impression.dx_part", lang, dx=_disease_id) if _disease_id else "",
                sev_part=t("clinical_impression.sev_part", lang, severity=_severity_label(_severity, lang))
                if _severity
                else "",
                phase=t(f"clinical_impression.phase.{_phase_key}", lang),
            )

        # CIF keeps both languages (AD-30: the JP description cannot
        # be re-derived from a code at FHIR emission time).
        description = _describe("en")
        description_ja = _describe("ja")
        records.append(
            ClinicalImpressionRecord(
                impression_id=f"{CLINICAL_IMPRESSION_ID_PREFIX}{encounter_id}-{day}",
                encounter_id=encounter_id,
                # Issue #821 (N-7): preserve the full datetime so
                # ClinicalImpression.effectiveDateTime carries time-of-day.
                # `day_dt` already includes admission_dt's HH:MM offset by
                # `timedelta(days=day)`; `.date()` was stripping it and
                # forcing date-only precision downstream, breaking
                # consumer time-series sort.
                date=day_dt,
                day_index=day,
                description=description,
                description_ja=description_ja,
                practitioner_id=attending_id,
                is_in_progress=last_day_of_in_progress,
                code_loinc=_code_loinc,
                code_loinc_display=_code_loinc_display,
            )
        )
    return records


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
    lang = lang_for(country)

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

        # Issue #1228: skip encounters that already have documents so this
        # enricher is idempotent when re-invoked at POST_RECORDS. The
        # immunization enricher (POST_RECORDS) appends companion vaccination
        # encounters (`ENC-VAX-*`, PR #1214) AFTER this enricher's
        # POST_ENCOUNTER pass has completed, then calls this enricher again
        # so the new encounters receive their document stubs. Existing
        # encounters (from POST_ENCOUNTER) must not re-emit — the guard is
        # "any document exists for this encounter_id" because a single
        # POST_ENCOUNTER pass emits every applicable spec (admission_once /
        # daily / daily_3shift / discharge_once / encounter_once) in one go.
        _encounters_with_docs: set[str] = {d.encounter_id for d in documents if d.encounter_id}

        for encounter in _o(record, "encounters", []) or []:
            enc_type_val = _enc_type_value(_o(encounter, "encounter_type", None))

            enc_status_val = _enc_status_value(_o(encounter, "status", None))
            if enc_status_val in _CANCELLED_STATUSES:
                continue  # AD-32: cancelled encounters produce no documents
            _enc_id_early = _o(encounter, "encounter_id", "") or ""
            if _enc_id_early and _enc_id_early in _encounters_with_docs:
                continue  # Issue #1228: already dispatched (idempotent re-invoke)

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
            facts = _EncounterFacts(
                record=record,
                encounter=encounter,
                encounter_id=encounter_id,
                pid=pid,
                admission_dt=admission_dt,
                discharge_dt=discharge_dt,
                los_days=los_days,
                config=ctx.config,
            )
            for spec in applicable_specs:
                planner = _PLANNERS.get(spec.generation_frequency)
                if planner is None:
                    continue
                built, doc_seq = _build_documents(
                    spec, planner(spec, facts), encounter, encounter_id, pid, lang, doc_seq
                )
                documents += built

            if enc_type_val == "inpatient":
                built, doc_seq = _ed_companion_documents(
                    encounter, encounter_id, admission_dt, country_spec_keys, pid, lang, doc_seq
                )
                documents += built

            # ── ClinicalImpression generation (inpatient types only; spec §3.3) ─
            if emit_ci:
                clinical_impressions += _clinical_impression_records(
                    encounter,
                    enc_type_val,
                    encounter_id,
                    admission_dt,
                    los_days,
                    is_in_progress,
                    attending_id,
                    country,
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
