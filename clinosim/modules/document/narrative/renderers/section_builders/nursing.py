"""ADMISSION_NURSING_ASSESSMENT (入院時看護アセスメント) +
NURSING_DISCHARGE_SUMMARY (看護サマリー) section builders.

Extracted verbatim from ``template_generator.TemplateNarrativeGenerator``
as step C1h of the full-review Phase C renderer split (CRITICAL C1).
Behavior is byte-identical.

Each builder is a free-standing ``(generator, ctx) -> (text, facts)``
function. The class methods of the same name become thin delegators so
``renderers/composition_sections.py`` (which looks up
``generator._build_<section>`` by name) stays unchanged.

Uses module-level helpers only (``_resolve_staff_name``, ``_label``,
``_localize_complication``, ``_lookup_nursing_content``, ``_o``, ``t``)
plus lazy imports for the Issue #1333 chronic-condition display chain
(``code_lookup`` + ``map_diagnosis_code``). No ``generator._*``
dispatch needed in this cluster.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from clinosim.codes import display as registry_display
from clinosim.locale.i18n import t
from clinosim.modules._shared import get_attr_or_key as _o
from clinosim.modules.document.narrative._localization import _localize_complication
from clinosim.modules.document.narrative._narrative_utils import _lookup_nursing_content
from clinosim.modules.document.narrative._template_helpers import _label, _resolve_staff_name, allergen_display
from clinosim.types.document import NarrativeContext

if TYPE_CHECKING:
    from clinosim.modules.document.narrative.template_generator import (
        TemplateNarrativeGenerator,
    )


# ─────────────────────────────────────────────────────────────────────
# ADMISSION_NURSING_ASSESSMENT section builders.
# ─────────────────────────────────────────────────────────────────────


def build_nursing_history(generator: TemplateNarrativeGenerator, ctx: NarrativeContext) -> tuple[str, list[str]]:
    """Build nursing_history from CIF (primary nurse + admission reason
    + chronic conditions + allergy summary). v9 density fix — v8
    emitted only a nurse id + generic fallback (~30 chars)."""
    facts: list[str] = []
    lang = ctx.target_lang

    parts: list[str] = []
    nurse_id = _o(ctx.encounter, "primary_nurse_id", "") or ""
    if nurse_id:
        facts.append("encounter.primary_nurse_id")
        nurse_disp = _resolve_staff_name(nurse_id, ctx.roster_map)
        parts.append(t("admission_status.assigned_nurse", lang, name=nurse_disp))
    cc = ""
    if ctx.encounter is not None:
        cc = _o(ctx.encounter, f"chief_complaint_{lang}", None) or _o(ctx.encounter, "chief_complaint", None) or ""
    if cc:
        parts.append(t("admission_status.admission_reason", lang, cc=cc))
    # Chronic summary — Issue #1333: route CIF base code through
    # map_diagnosis_code so display matches the FHIR emit-target.
    from clinosim.modules.output.fhir_r4.lib.common import (
        map_diagnosis_code as _map_diagnosis_code,
    )

    country = "JP" if ctx.locale.lower() == "jp" else "US"
    conds = _o(ctx.patient, "chronic_conditions", []) or [] if ctx.patient else []
    labels: list[str] = []
    for c in conds[:4]:
        code = _o(c, "code", "") or (c if isinstance(c, str) else "")
        if not code:
            continue
        emit_code = _map_diagnosis_code(code, country) or code
        key = "icd-10" if ctx.locale == "jp" else "icd-10-cm"
        labels.append(registry_display(key, emit_code, ctx.target_lang) or emit_code)
    if labels:
        parts.append(
            t("pmh.header_prefix", lang) + t("list_sep.serial", lang).join(labels) + t("list_sep.period", lang)
        )
    # Allergy
    allergies = ctx.allergies or []
    if allergies:
        first_allergen = next((d for a in allergies if (d := allergen_display(a, lang))), "")
        if first_allergen:
            parts.append(t("admission_status.allergy_first", lang, allergen=first_allergen))
    if len(parts) <= 1:
        parts.append(t("fallback.nursing_history_fallback", lang))
    facts.extend(["ctx.encounter.chief_complaint", "ctx.patient.chronic_conditions"])
    return "".join(parts), facts


def build_adl_assessment(generator: TemplateNarrativeGenerator, ctx: NarrativeContext) -> tuple[str, list[str]]:
    """Build adl_assessment from CIF adl_assessments (Barthel Index).
    v9 density fix — v8 emitted 12-char "ADL：自立（問題なし）"."""
    facts: list[str] = []
    lang = ctx.target_lang
    adls = list(getattr(ctx, "adl_assessments", None) or [])
    if not adls:
        return (t("fallback.adl_fallback", lang)), facts
    latest = adls[-1]
    barthel = _o(latest, "barthel_score", None)
    if barthel is None:
        return (t("fallback.adl_fallback", lang)), facts
    facts.append("ctx.adl_assessments[-1]")
    # Barthel band interpretation (standard)
    if barthel >= 91:
        band = t("barthel_band.independent", lang)
    elif barthel >= 61:
        band = t("barthel_band.minimal_assist", lang)
    elif barthel >= 41:
        band = t("barthel_band.moderate_assist", lang)
    elif barthel >= 21:
        band = t("barthel_band.severe_dependence", lang)
    else:
        band = t("barthel_band.total_care", lang)
    detail_parts: list[str] = []
    for k in ("feeding", "bathing", "mobility", "toilet_use"):
        v = _o(latest, k, None)
        if v is not None:
            label = _label("adl_detail_key", k, lang, fallback=k)
            detail_parts.append(t("adl_detail.item", lang, label=label, score=v))
    detail = t("adl_detail.wrap", lang, items=t("list_sep.serial", lang).join(detail_parts)) if detail_parts else ""
    return f"Barthel Index {barthel}/100 → {band}{detail}", facts


def build_risk_assessments(generator: TemplateNarrativeGenerator, ctx: NarrativeContext) -> tuple[str, list[str]]:
    """Build risk_assessments from CIF (Braden + Morse). v9 density
    fix — v8 emitted 12-char placeholder."""
    facts: list[str] = []
    lang = ctx.target_lang
    risks = list(getattr(ctx, "nursing_risk_assessments", None) or [])
    if not risks:
        return (t("fallback.risk_fallback", lang)), facts
    latest = risks[-1]
    braden = _o(latest, "braden_total", None)
    morse = _o(latest, "morse_total", None)
    fall_lvl = _o(latest, "fall_risk_level", None)
    facts.append("ctx.nursing_risk_assessments[-1]")
    parts: list[str] = []
    if braden is not None:
        # Braden risk bands: >18 low / 15-18 mild / 13-14 moderate / 10-12 high / ≤9 severe
        if braden >= 19:
            bband = t("morse_band.low", lang)
        elif braden >= 15:
            bband = t("morse_band.mild", lang)
        elif braden >= 13:
            bband = t("morse_band.moderate", lang)
        elif braden >= 10:
            bband = t("morse_band.high", lang)
        else:
            bband = t("morse_band.severe", lang)
        parts.append(t("risk.braden_line", lang, braden=braden, band=bband))
    if morse is not None:
        lvl = fall_lvl or ("low" if morse < 25 else "moderate" if morse < 45 else "high")
        # Localize the fall-risk enum via the shared morse_band phrase
        # catalog so JA emits 「低リスク / 中等度リスク / 高リスク」
        # instead of the raw EN token. Unknown values fall back to
        # the raw string.
        lvl_key = str(lvl).lower()
        lvl_disp = t(f"morse_band.{lvl_key}", lang)
        if lvl_disp == f"morse_band.{lvl_key}":
            lvl_disp = str(lvl)
        parts.append(t("fall_risk.morse_score_line", lang, morse=morse, level=lvl_disp))
    if not parts:
        return (t("fallback.risk_fallback", lang)), facts
    # Phase 1d-70: use ``period_space`` between sentences so EN
    # emits ``low. Fall (...): moderate.`` rather than the
    # spaceless ``low.Fall (...): moderate.`` — JA ``。`` already
    # needs no space and both variants collapse to the same char.
    return t("list_sep.period_space", lang).join(parts) + t("list_sep.period", lang), facts


def build_nursing_diagnosis(generator: TemplateNarrativeGenerator, ctx: NarrativeContext) -> tuple[str, list[str]]:
    """Build nursing_diagnosis from CIF chronic conditions + acute
    admission reason + risk data.

    Session-104 Tier 2: acute-disease axis (from
    ``ctx.disease_protocol.disease_id``) is consulted BEFORE the
    chronic-ICD10 axis via ``_lookup_nursing_content``. Both axes
    are backed by ``clinosim-nursing-content.yaml`` — the 6 chronic
    prefixes are carried over verbatim, so byte-diff on encounters
    without a pilot acute match is zero.

    Risk-derived NDx (fall / pressure ulcer) are appended after
    the YAML-driven items — same behavior as pre-session-104.
    """
    lang = ctx.target_lang
    dx_labels, facts = _lookup_nursing_content(ctx, "nursing_diagnoses", lang, cap=5)

    # Risk-derived NDx (unchanged from pre-session-104 semantics —
    # appended on top of the YAML-driven items, past the cap).
    risks = list(getattr(ctx, "nursing_risk_assessments", None) or [])
    if risks:
        latest = risks[-1]
        fall = _o(latest, "fall_risk_level", None)
        if fall and str(fall).lower() in ("high", "moderate"):
            fr = t("fall_risk.short_label", lang)
            if fr not in dx_labels:
                dx_labels.append(fr)
                if "ctx.nursing_risk_assessments" not in facts:
                    facts.append("ctx.nursing_risk_assessments")
        braden = _o(latest, "braden_total", None)
        if braden is not None and braden <= 14:
            pu = t("nursing.pu_risk_label", lang)
            if pu not in dx_labels:
                dx_labels.append(pu)
                if "ctx.nursing_risk_assessments" not in facts:
                    facts.append("ctx.nursing_risk_assessments")

    if dx_labels:
        head = t("nursing.diagnoses_head", lang)
        sep = t("list_sep.serial", lang)
        return head + sep.join(dx_labels) + t("list_sep.period", lang), facts
    return (t("fallback.nursing_dx_fallback", lang)), facts


def build_care_plan(generator: TemplateNarrativeGenerator, ctx: NarrativeContext) -> tuple[str, list[str]]:
    """Build care_plan from CIF-derived nursing diagnoses (mirror of
    _build_nursing_diagnosis interventions).

    Session-104 Tier 2: acute-disease axis (from
    ``ctx.disease_protocol.disease_id``) is consulted BEFORE the
    chronic-ICD10 axis via ``_lookup_nursing_content``. The 6
    chronic prefixes carry over verbatim, so byte-diff on
    non-pilot encounters is zero. Risk-driven actions (fall / PU
    precautions) are appended after the YAML-driven items — same
    as pre-session-104.
    """
    lang = ctx.target_lang
    actions, facts = _lookup_nursing_content(ctx, "care_plan", lang, cap=4)

    # Risk-driven actions. Semantic-prefix dedup (session-104): the
    # acute YAML entry for cerebral_infarction (and future pilots)
    # already emits a "fall precautions" line — appending the
    # risk-derived version would double-cover. Skip whenever ANY
    # existing action already opens with the fall-precaution /
    # PU-prevention prefix (locale-specific).
    risks = list(getattr(ctx, "nursing_risk_assessments", None) or [])
    _fall_prefix = t("nursing.fall_precautions", lang)
    _pu_prefix = t("nursing.pu_prevention", lang)
    if risks:
        latest = risks[-1]
        if str(_o(latest, "fall_risk_level", "") or "").lower() in ("high", "moderate"):
            if not any(a.startswith(_fall_prefix) for a in actions):
                actions.append(t("nursing.fall_precautions_action", lang))
                if "ctx.nursing_risk_assessments" not in facts:
                    facts.append("ctx.nursing_risk_assessments")
        if (_o(latest, "braden_total", 25) or 25) <= 14:
            if not any(a.startswith(_pu_prefix) for a in actions):
                actions.append(t("nursing.pu_prevention_action", lang))
                if "ctx.nursing_risk_assessments" not in facts:
                    facts.append("ctx.nursing_risk_assessments")

    if actions:
        head = t("nursing.care_plan_head", lang)
        sep = t("list_sep.semicolon", lang)
        return head + sep.join(actions) + t("list_sep.period", lang), facts
    return (t("fallback.care_plan_fallback", lang)), facts


# ─────────────────────────────────────────────────────────────────────
# NURSING_DISCHARGE_SUMMARY section builders.
# ─────────────────────────────────────────────────────────────────────


def build_nursing_admission_status(
    generator: TemplateNarrativeGenerator, ctx: NarrativeContext
) -> tuple[str, list[str]]:
    """Build admission_status for NURSING_DISCHARGE_SUMMARY. v9 density fix:
    include admission reason + complications summary."""
    facts: list[str] = []
    lang = ctx.target_lang
    los = ctx.los_days or 1
    facts.append("ctx.los_days")
    cc = ""
    if ctx.encounter is not None:
        cc = _o(ctx.encounter, f"chief_complaint_{lang}", None) or _o(ctx.encounter, "chief_complaint", None) or ""
    comps = list(getattr(ctx, "complications_occurred", []) or [])
    # Phase 1c-2 (2026-09-22): localize complication tokens (31 leaks
    # in JP p=500 admission_status audit — "経過中の合併症: urosepsis"
    # → "経過中の合併症: 尿路性敗血症").
    comp_labels = [_localize_complication(str(c), lang) for c in comps[:3]]
    parts: list[str] = [t("nursing_admission_status.stay_head", lang, los=los)]
    if cc:
        parts.append(t("nursing_admission_status.admission_reason_line", lang, cc=cc))
    if comp_labels:
        sep = t("list_sep.serial", lang)
        parts.append(t("nursing_admission_status.complications_line", lang, list=sep.join(comp_labels)))
        facts.append("ctx.complications_occurred")
    parts.append(t("nursing_admission_status.discharge_met_line", lang))
    return "".join(parts), facts


def build_nursing_interventions_provided(
    generator: TemplateNarrativeGenerator, ctx: NarrativeContext
) -> tuple[str, list[str]]:
    """Build nursing_interventions_provided from CIF procedures / MAR /
    intake-output totals. v9 density fix — v8 emitted 15-char placeholder."""
    facts: list[str] = []
    lang = ctx.target_lang
    parts: list[str] = []
    procs = [_o(pr, "procedure_name", None) or _o(pr, "name", None) for pr in (ctx.procedures or [])[:5]]
    procs = [p for p in procs if p]
    if procs:
        facts.append("ctx.procedures")
        parts.append(
            t("discharge_readiness.procedures_head", lang) + t("list_sep.serial", lang).join(str(p) for p in procs)
        )
    # Intake/output totals
    io = list(getattr(ctx, "intake_output_records", None) or [])
    if io:
        total_in = sum(_o(r, "intake_iv_ml", 0) + _o(r, "intake_oral_ml", 0) + _o(r, "intake_other_ml", 0) for r in io)
        total_out = sum(
            _o(r, "output_urine_ml", 0) + _o(r, "output_drain_ml", 0) + _o(r, "output_other_ml", 0) for r in io
        )
        facts.append("ctx.intake_output_records")
        parts.append(
            t("nursing_interventions.io_line", lang, in_ml=total_in, out_ml=total_out, net=total_in - total_out)
        )
    if parts:
        return t("list_sep.semicolon", lang).join(parts) + t("list_sep.period", lang), facts
    return (t("fallback.interventions_fallback", lang)), facts


def build_patient_education(generator: TemplateNarrativeGenerator, ctx: NarrativeContext) -> tuple[str, list[str]]:
    """Build patient_education from chronic conditions + acute
    admission reason.

    Session-104 Tier 2: acute-disease axis (from
    ``ctx.disease_protocol.disease_id``) is consulted BEFORE the
    chronic-ICD10 axis via ``_lookup_nursing_content``. The 6
    chronic prefixes carry over verbatim from the pre-session-104
    hardcoded map, so byte-diff on non-pilot encounters is zero.
    No risk-derived rows here (unlike nursing_diagnosis /
    care_plan) — patient education is disease-driven only.
    """
    lang = ctx.target_lang
    topics, facts = _lookup_nursing_content(ctx, "patient_education", lang, cap=4)
    if not topics:
        return (t("fallback.patient_education_fallback", lang)), facts
    head = t("patient_education.head", lang)
    sep = t("list_sep.semicolon", lang)
    return head + sep.join(topics) + t("list_sep.period", lang), facts


def build_discharge_readiness(generator: TemplateNarrativeGenerator, ctx: NarrativeContext) -> tuple[str, list[str]]:
    """Build discharge_readiness from latest ADL + risk. v9 density fix."""
    facts: list[str] = []
    lang = ctx.target_lang
    adls = list(getattr(ctx, "adl_assessments", None) or [])
    risks = list(getattr(ctx, "nursing_risk_assessments", None) or [])
    parts: list[str] = []
    if adls:
        latest = adls[-1]
        barthel = _o(latest, "barthel_score", None)
        if barthel is not None:
            facts.append("ctx.adl_assessments[-1]")
            parts.append(t("rehab.discharge_barthel_line", lang, score=barthel))
    if risks:
        latest = risks[-1]
        fall = _o(latest, "fall_risk_level", None)
        braden = _o(latest, "braden_total", None)
        if fall or braden is not None:
            facts.append("ctx.nursing_risk_assessments[-1]")
            bits = []
            if fall:
                # Localize fall_risk_level via the shared morse_band
                # catalog (JA emits 「低リスク / 中等度リスク / 高リスク」
                # rather than the raw EN token). Unknown values fall
                # back to the raw string.
                fall_key = str(fall).lower()
                fall_disp = t(f"morse_band.{fall_key}", lang)
                if fall_disp == f"morse_band.{fall_key}":
                    fall_disp = str(fall)
                bits.append(t("rehab.fall_suffix", lang, label=fall_disp))
            if braden is not None:
                bits.append(f"Braden {braden}")
            parts.append(t("list_sep.serial", lang).join(bits))
    if parts:
        head = t("discharge_readiness.head", lang)
        return head + (t("list_sep.semicolon", lang).join(parts)) + t("list_sep.period", lang), facts
    return (t("fallback.discharge_readiness_fallback", lang)), facts
