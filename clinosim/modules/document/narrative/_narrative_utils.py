"""Miscellaneous narrative helpers for template-driven generation.

Third mechanical slice of the META #1633 P6 narrative-package
decomposition (first ``_localization.py``, second
``_template_helpers.py``). This module collects the remaining
pre-``TemplateNarrativeGenerator`` helpers: nursing-content lookup,
per-day vitals filtering, deterministic SHA-driven decision gates
(autopsy performed), age arithmetic from the narrative context,
ISO-datetime parsing with fallbacks, chief-complaint keyword
matching, encounter-salted pool pickers (for pathology-exam text
variants), and physical-exam clause rewriting.

These are grouped together because each is used by multiple
sections of the god class, has no shared mutable state with the
others, and does not fit the ``_localization`` or
``_template_helpers`` concerns. ``template_generator.py`` re-exports
every name verbatim so external callers and tests keep their import
paths unchanged.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from functools import cache
from pathlib import Path
from typing import Any

from clinosim.modules._shared import get_attr_or_key as _o
from clinosim.types.document import NarrativeContext


def _lookup_nursing_content(ctx: NarrativeContext, field: str, lang: str, cap: int) -> tuple[list[str], list[str]]:
    """Session 104 Tier 2: merge acute-disease + chronic-ICD10 nursing
    content items for the given field
    (``"nursing_diagnoses" / "care_plan" / "patient_education"``).

    Merge order: acute (from ``ctx.disease_protocol.disease_id``) first,
    chronic (from ``ctx.patient.chronic_conditions[].code``) second.
    Items are deduplicated by exact-string equality and capped at
    ``cap`` items total. Facts-used trace lists the two sources
    consulted so the downstream ``facts_used`` field stays honest.

    Returns ``(items, facts)``. When the YAML is unavailable or
    matches nothing, returns ``([], [])`` — callers fall back to their
    existing sentinel-fallback strings (byte-identical to the
    pre-session-104 chronic-only path for non-pilot encounters).
    """
    from clinosim.modules.document.reference_data_loaders import (
        load_nursing_content,
    )

    try:
        data = load_nursing_content()
    except (FileNotFoundError, ValueError, OSError):
        return [], []

    items: list[str] = []
    facts: list[str] = []
    seen: set[str] = set()

    # --- Acute-first: ctx.disease_protocol.disease_id anchor ----------
    disease_id = ""
    if ctx.disease_protocol is not None:
        disease_id = getattr(ctx.disease_protocol, "disease_id", "") or ""
    acute_axis = data.get("acute_disease") or {}
    if disease_id and disease_id in acute_axis:
        entry = acute_axis[disease_id]
        acute_items = (entry.get(field) or {}).get(lang) or []
        for x in acute_items:
            if not x or x in seen:
                continue
            items.append(x)
            seen.add(x)
            if len(items) >= cap:
                break
        if items:
            facts.append("ctx.disease_protocol.disease_id")

    # --- Chronic-second: ctx.patient.chronic_conditions ---------------
    chronic_axis = data.get("chronic_icd10") or {}
    conds = _o(ctx.patient, "chronic_conditions", []) or [] if ctx.patient is not None else []
    added_chronic = False
    for c in conds[:5]:
        if len(items) >= cap:
            break
        code = _o(c, "code", "") or (c if isinstance(c, str) else "")
        prefix = str(code).split(".")[0].upper() if code else ""
        entry = chronic_axis.get(prefix)
        if not entry:
            continue
        chronic_items = (entry.get(field) or {}).get(lang) or []
        for x in chronic_items:
            if not x or x in seen:
                continue
            items.append(x)
            seen.add(x)
            added_chronic = True
            if len(items) >= cap:
                break
    if added_chronic:
        facts.append("ctx.patient.chronic_conditions")

    return items, facts


def _filter_vitals_for_day(vitals: list, day_index: int, encounter: Any) -> list:
    """Return vitals belonging to day ``day_index`` of the stay.

    v6 (2026-08-16): CIF vital_signs records store ISO ``timestamp`` but
    ``day`` is typically None. The naive day-field filter therefore let
    admission-day vitals leak into every day's context, producing "T=38.1°C
    repeated for 15 consecutive progress notes" hallucinations (POP-000075).

    v7 (session 104, Issue #1166): timestamp bucketing now uses
    **calendar day** offset rather than 24h-window offset. Pre-v7 the
    delta computation was ``(ts - adm_dt).days`` which floors sub-daily
    admission times: an admission at 2026-03-19T20:23 (evening) bucketed
    2026-03-20T23:55 vitals AND 2026-03-21T18:00 vitals into the same
    day_index=1 slot (both fall within 24-48h of admission). The
    resulting doc labeled "Hospital day 2" (= day_index=1) then showed
    vitals from two calendar days, causing the LLM to write "new fever
    spike to 38.5°C" (a day 2026-03-21 reading) inside an Objective
    section that displayed the 2026-03-20 evening T=36.8°C reading —
    a subtle Grounding drift that reads as fabrication.

    v7 changes the offset to ``(ts.date() - adm_dt.date()).days`` so
    day_index=N aligns with the Nth calendar day since admission
    (day_index=0 = admission calendar day, day_index=1 = next calendar
    day, etc.). This matches the ``hospital_day_label`` rendering
    (``"hospital day {day_index+1}"``) that the LLM sees, so a doc
    labeled "Hospital day 2" surfaces exactly the 2026-03-20 vitals
    and never the 2026-03-21 spike.

    Resolution order:
      1. If any record has an explicit ``day`` field, match on it.
      2. Otherwise derive a calendar-day offset from ``timestamp.date()``
         minus ``encounter.admission_datetime.date()``.
      3. If neither exists, fall back to the first record (initial vitals).
    """
    vitals = list(vitals or [])
    if not vitals:
        return []
    # 1. Explicit day field
    tagged = [v for v in vitals if _o(v, "day", None) == day_index]
    if tagged:
        return tagged
    any_tagged = any(_o(v, "day", None) is not None for v in vitals)
    if any_tagged:
        # Some records have day, none matched → this day has none.
        return []
    # 2. Calendar-day offset fallback
    adm_raw = _o(encounter, "admission_datetime", None) if encounter is not None else None
    adm_dt = _parse_iso_datetime(adm_raw)
    if adm_dt is None:
        # Use earliest timestamp as day-0 anchor
        candidates: list[datetime] = [
            c for c in (_parse_iso_datetime(_o(v, "timestamp", None)) for v in vitals) if c is not None
        ]
        if candidates:
            adm_dt = min(candidates)
    if adm_dt is None:
        return vitals[:1]
    adm_date = adm_dt.date()
    picks: list = []
    for v in vitals:
        ts = _parse_iso_datetime(_o(v, "timestamp", None))
        if ts is None:
            continue
        # Session-104 v7: calendar-day bucket, not 24h-window bucket.
        offset = (ts.date() - adm_date).days
        if offset == day_index:
            picks.append(v)
    if picks:
        return picks
    return vitals[:1]


# Issue #961 extension: RNG-neutral autopsy sampling (used by both the
# 死亡診断書 autopsy_status section and the 死亡退院サマリー
# autopsy_status_and_findings section so the two documents agree per
# encounter). Cutoff p=0.07 gives ~7% autopsy rate matching the low
# end of JMA / MHLW real-world autopsy statistics for JP acute care.
# SHA256 keyed on (encounter_id, patient_id, "autopsy") is deterministic
# across regens and does not consume the master RNG
# (feedback_rng_neutral_additive_field).
_DDS_AUTOPSY_PROB_CUTOFF = int((1 << 64) * 0.07)


def _autopsy_performed_sha256(ctx: NarrativeContext) -> bool:
    """Deterministic per-encounter autopsy sample. See module comment above."""

    enc_id = _o(getattr(ctx, "encounter", None), "encounter_id", "") or ""
    pat_id = getattr(ctx.patient, "patient_id", "") if ctx.patient else ""
    key = f"{enc_id}|{pat_id}|autopsy".encode()
    h = int.from_bytes(hashlib.sha256(key).digest()[:8], "big")
    return h < _DDS_AUTOPSY_PROB_CUTOFF


def _age_at(ctx: NarrativeContext) -> int | None:
    """Age of ``ctx.patient`` at the ``ctx.encounter`` date.

    ``PatientProfile.age`` is a static field set at cohort-generation
    time. Encounters happen months to years later along the simulation
    window, so reading ``patient.age`` directly under-reports by 1-2 y
    (birthday not yet passed / multi-year window). Prefer this helper
    on any narrative that quotes the patient's age at a specific visit
    (Issue #1173: 95.1% of SOAP progress-note headers off-by-1-or-2).

    Returns the correctly-aged integer when both ``date_of_birth`` and
    encounter date are available; falls back to ``patient.age`` when
    either is missing.
    """
    patient = getattr(ctx, "patient", None)
    if patient is None:
        return None
    static_age = _o(patient, "age", None)
    dob_raw = _o(patient, "date_of_birth", None)
    if dob_raw is None:
        return static_age
    # #1173 verify follow-up (2nd pass): CIF can carry `date_of_birth`
    # as either a `date` object (typed CIF) or an ISO string like
    # `"1990-06-25"` (CIF reader on serialized JSON). `dob.year` on a
    # string raises AttributeError which the try/except below silently
    # swallowed, and the helper fell back to static age — so 94-96% of
    # SOAP headers still reported the stale age. Normalize string DOB
    # here so both representations reach the year arithmetic.
    from datetime import date as _date

    dob: _date | None
    if isinstance(dob_raw, str):
        try:
            dob = _date.fromisoformat(dob_raw[:10])
        except ValueError:
            return static_age
    elif hasattr(dob_raw, "year") and hasattr(dob_raw, "month") and hasattr(dob_raw, "day"):
        dob = dob_raw
    else:
        return static_age
    enc = getattr(ctx, "encounter", None)
    ref_dt = _o(enc, "admission_datetime", None) if enc is not None else None
    if ref_dt is None:
        return static_age
    try:
        if isinstance(ref_dt, str):
            ref = _date.fromisoformat(ref_dt[:10])
        elif isinstance(ref_dt, datetime):
            ref = ref_dt.date()
        else:
            ref = ref_dt
        years = ref.year - dob.year - (1 if (ref.month, ref.day) < (dob.month, dob.day) else 0)
        if years < 0:
            return static_age
        return years
    except (AttributeError, TypeError, ValueError):
        return static_age


def _parse_iso_datetime(raw: Any) -> datetime | None:
    """Best-effort parse of an ISO 8601 datetime string / datetime object."""
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw
    if not isinstance(raw, str):
        return None
    s = raw.strip()
    if not s:
        return None
    # Python's fromisoformat handles the common cases; tolerate trailing Z.
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        # Fall back to date-only strings
        try:
            return datetime.fromisoformat(s[:10])
        except ValueError:
            return None


# ─────────────────────────────────────────────────────────────────
# Issue #979 / #980: CC × physical_examination consistency helpers
# ─────────────────────────────────────────────────────────────────
#
# Template-first fix (per user directive): the physical_examination narrative
# must be internally coherent with the chief_complaint from CIF alone, without
# an LLM refinement pass. Two problem classes were observed at seed 1000
# p=2000 (Issue #980):
#   * 39 records: CC 意識障害 + PE 意識清明
#   * 47 records: CC 呼吸困難 + PE 呼吸音清明
#
# Fix: after `_format_physical_exam` produces its per-body-system prose, run
# it through `_apply_cc_pe_consistency`, which detects altered-consciousness
# or severe-dyspnea CC and rewrites the matching PE clause with a clinically
# plausible finding drawn from a small pool by SHA256(encounter_id) — this
# keeps the transform deterministic and RNG-neutral
# (feedback_rng_neutral_additive_field).

# CC keyword / PE replacement pools now live in
# `clinosim/codes/data/cc-pe-consistency-keywords.yaml`. The accessors
# below load them lazily; the clinical rationale (altered consciousness
# CC must not co-exist with 「意識清明」 PE; severe dyspnea CC must not
# co-exist with 「呼吸音清明」 PE; replacement is deterministic via
# SHA256(encounter_id)) is captured in the yaml's metadata block.


@cache
def _cc_pe_consistency_keywords() -> dict[str, Any]:
    """Load `clinosim/codes/data/cc-pe-consistency-keywords.yaml`."""
    import yaml

    path = Path(__file__).resolve().parents[3] / "codes" / "data" / "cc-pe-consistency-keywords.yaml"
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def _cc_altered_consciousness_keywords() -> tuple[str, ...]:
    rows = (_cc_pe_consistency_keywords().get("cc_keywords") or {}).get("altered_consciousness") or []
    return tuple(str(r) for r in rows if isinstance(r, str))


def _cc_severe_dyspnea_keywords() -> tuple[str, ...]:
    rows = (_cc_pe_consistency_keywords().get("cc_keywords") or {}).get("severe_dyspnea") or []
    return tuple(str(r) for r in rows if isinstance(r, str))


def _cc_negation_tokens_right() -> tuple[str, ...]:
    rows = (_cc_pe_consistency_keywords().get("negation_tokens") or {}).get("right") or []
    return tuple(str(r) for r in rows if isinstance(r, str))


def _pe_altered_consciousness_pool_ja() -> tuple[str, ...]:
    rows = (_cc_pe_consistency_keywords().get("pe_replacement_pool") or {}).get("altered_consciousness") or []
    return tuple(str(r) for r in rows if isinstance(r, str))


def _pe_severe_dyspnea_pool_ja() -> tuple[str, ...]:
    rows = (_cc_pe_consistency_keywords().get("pe_replacement_pool") or {}).get("severe_dyspnea") or []
    return tuple(str(r) for r in rows if isinstance(r, str))


def _cc_keyword_positively_present(cc_text: str, keywords: tuple[str, ...]) -> bool:
    """Return True if any keyword appears in ``cc_text`` and is NOT negated
    by a right-adjacent negation token (なし / 認めず / 否定 / etc.).

    Detection window: 6 characters after the keyword's end. This matches the
    JP chief_complaint style seen in practice — negation follows immediately
    (「意識障害なし」「呼吸困難認めず」).
    """
    if not cc_text:
        return False
    for kw in keywords:
        start = 0
        while True:
            idx = cc_text.find(kw, start)
            if idx < 0:
                break
            end = idx + len(kw)
            tail = cc_text[end : end + 6]
            if not any(neg in tail for neg in _cc_negation_tokens_right()):
                return True
            start = end
    return False


def _pick_from_pool_by_encounter(pool: tuple[str, ...], enc_id: str, salt: str) -> str:
    """Deterministic pool pick keyed on (encounter_id, salt).

    RNG-neutral (SHA256, does not consume master RNG). Same encounter always
    picks the same phrase — so byte-diff-across-regens holds.
    """

    key = f"{enc_id or 'ENC-UNKNOWN'}|{salt}".encode()
    idx = hashlib.sha256(key).digest()[0] % len(pool)
    return pool[idx]


def _rewrite_pe_clause(text: str, trigger_substrings: tuple[str, ...], replacement: str) -> str:
    """Rewrite each clause in ``text`` that contains any trigger substring.

    ``text`` is the joined per-body-system prose from `_format_physical_exam`
    — clauses are separated by 「。」 for JA (see `_format_physical_exam`
    return). Body-system labels ("一般状態:", "呼吸器:", …) sit at the head
    of each clause; we preserve the label and replace only the value portion
    after the first "：" or ": ".

    Returns ``text`` unchanged if no trigger fires.
    """
    if not text:
        return text
    clauses = text.split("。")
    changed = False
    for i, clause in enumerate(clauses):
        if not any(t in clause for t in trigger_substrings):
            continue
        # Split "label: value" on the first ": " (or "：") and keep the label.
        # `_format_physical_exam` uses ASCII ": " (see lines 5181-5183).
        if ": " in clause:
            label, _sep, _ = clause.partition(": ")
            clauses[i] = f"{label}: {replacement}"
            changed = True
        else:
            # No label prefix — replace the whole clause.
            clauses[i] = replacement
            changed = True
    if not changed:
        return text
    return "。".join(clauses)
