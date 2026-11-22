"""OUTPATIENT_SOAP section builders — subjective / objective /
assessment / plan.

Extracted verbatim from ``template_generator.TemplateNarrativeGenerator``
as step C1l of the full-review Phase C renderer split (CRITICAL C1).
Behavior is byte-identical.

Each builder is a free-standing ``(generator, ctx) -> (text, facts)``
function. The class methods of the same name become thin delegators so
``renderers/composition_sections.py`` (which looks up
``generator._build_<section>`` by name) stays unchanged.

Outpatient-only helpers that moved with the builders (all previously
on the class, grep-verified to have no callers outside the outpatient
cluster):
  - ``_get_soap_template`` (3-layer template resolver)
  - ``_compose_outpatient_subjective_from_state``
  - ``_compose_ed_assessment_from_state``
  - ``_compose_encounter_reason_line``
  - ``_compose_chronic_condition_line``
  - ``_compose_chronic_assessment_integrated``
  - ``_compose_today_prescription_line``
  - ``_compose_today_procedures_line``
  - ``_compose_follow_up_line``
  - ``_compose_current_medications_line``
  - ``_chronic_med_class_hints_raw`` + ``_chronic_med_class_hints``
    (module-level YAML loader, moved from template_generator.py)

Generator-threaded helpers (stay on the class):
  - ``generator._compose_vital_signs_line`` (outpatient_objective)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

from clinosim.codes import display as registry_display
from clinosim.codes.drugs import drug_key, medication_matches
from clinosim.codes.valuesets import concept_group, iter_chronic_codes
from clinosim.countries import country_code, has_authored_narrative
from clinosim.locale.i18n import t
from clinosim.locale.loader import chronic_followup_interval_months, load_chronic_followup
from clinosim.locale.loader import narrative_label as _label
from clinosim.modules._shared import drug_spec_in_age_band, strip_protocol_prefix
from clinosim.modules._shared import get_attr_or_key as _o
from clinosim.modules.document.narrative._interval_events import interval_event_line, interval_events
from clinosim.modules.document.narrative._localization import _localize_complication, _localize_stage
from clinosim.modules.document.narrative._narrative_interpretation_thresholds import (
    NARRATIVE_HBA1C_DIABETES_THRESHOLD,
    bp_control,
    bp_target,
    chronic_control_targets,
    is_tachycardic_hr,
)
from clinosim.modules.document.narrative._narrative_utils import _age_at
from clinosim.modules.document.narrative._next_visit import next_visit_days
from clinosim.modules.document.narrative._outpatient_results import (
    ckd_g_stage,
    known_labs,
    outpatient_results,
    pending_lab_names,
    prior_lab_values,
    screening_scores,
    stage_from_pending_lab,
)
from clinosim.modules.document.narrative._prescription_line import prescription_bits
from clinosim.modules.document.narrative._template_helpers import (
    _pick_localized,
    _render_home_med_name,
    _render_safety_skips_line,
)
from clinosim.modules.document.narrative._visit_reason import (
    join_sentences,
    kind_lines,
    kind_values,
    known_conditions_tail,
    next_visit_line,
    visit_dx,
    visit_kind,
    vital_findings,
)
from clinosim.modules.document.narrative.renderers._shared_helpers import (
    chronic_condition_label,
    ordered_chronic_conditions,
)
from clinosim.modules.document.narrative.renderers.section_builders._registry import section
from clinosim.modules.document.narrative.renderers.section_builders.chief_complaint import encounter_chief_complaint
from clinosim.modules.document.narrative.renderers.section_builders.patient_history import (
    home_medications_at_admission,
)
from clinosim.modules.document.reference_data_loaders import AsthmaControlInstruments, ChronicMedClassHints
from clinosim.modules.observation.pediatric_ranges import age_in_completed_months, pediatric_vital_range
from clinosim.reference_data import load_reference_yaml
from clinosim.simulator.statin_monitoring import ldl_risk_threshold as statin_ldl_risk_threshold
from clinosim.simulator.statin_monitoring import ldl_target as statin_ldl_target
from clinosim.simulator.statin_monitoring import on_maximal_statin, statin_monitoring_rules
from clinosim.types.document import DocumentType, NarrativeContext

if TYPE_CHECKING:
    from clinosim.modules.document.narrative.template_generator import (
        TemplateNarrativeGenerator,
    )


# ─────────────────────────────────────────────────────────────────────
# Chronic-med-class hints loader (moved from template_generator.py —
# only consumer was _compose_chronic_assessment_integrated, now below).
# ─────────────────────────────────────────────────────────────────────


@cache
def _chronic_med_class_hints_raw() -> dict[str, dict[str, Any]]:
    """Load `reference_data/chronic-med-class-hints.yaml`.

    Returns a `{class_key: {prefix, en: [...], ja: [...]}}` dict.
    """
    raw = load_reference_yaml(
        Path(__file__).resolve().parents[4] / "document" / "reference_data" / "chronic-med-class-hints.yaml"
    )
    ChronicMedClassHints.model_validate(raw)
    classes = raw.get("classes") or {}
    out: dict[str, dict[str, Any]] = {}
    for class_key, row in classes.items():
        if isinstance(row, dict):
            out[str(class_key)] = row
    return out


def _chronic_med_class_hints(class_key: str, lang: str) -> tuple[str, ...]:
    """Medication-name hints of a chronic-condition class in ``lang`` (then
    English), from `chronic-med-class-hints.yaml` (`hypertension`, `diabetes`,
    `dyslipidemia`, `afib_anticoagulation`, `copd`, `asthma`). The hints match
    the medication names as rendered in that language; a missing list returns
    `()`, which `_pick_med_containing` treats as "no med cited"."""
    from clinosim.locale.localized import normalize_lang

    row = _chronic_med_class_hints_raw().get(class_key) or {}
    hints = row.get(normalize_lang(lang)) or row.get("en") or []
    return tuple(str(h) for h in hints if isinstance(h, str))


@cache
def _asthma_control_bands() -> tuple[dict[str, Any], ...]:
    """Age bands of `asthma-control-instruments.yaml` (Issue #3264)."""
    raw = load_reference_yaml(
        Path(__file__).resolve().parents[4] / "document" / "reference_data" / "asthma-control-instruments.yaml"
    )
    AsthmaControlInstruments.model_validate(raw)
    return tuple(raw["bands"])


def _asthma_control_phrase_key(age: int | None) -> str:
    """The phrase key of the asthma control instrument for ``age``: the ACT
    from 12 years, the Childhood ACT for 4-11, a caregiver symptom review
    below 4 (GINA 2024). An unknown age takes the adult instrument."""
    bands = _asthma_control_bands()
    if age is None:
        return str(bands[0]["phrase"])
    for b in bands:
        if drug_spec_in_age_band(b, age):
            return str(b["phrase"])
    return str(bands[0]["phrase"])


# Lab names (lowercase) one source supplies together when a visit has none of
# them (Issue #3273): renal function and the blood count are never mixed from
# a visit and an earlier one.
_LAB_GROUPS: tuple[tuple[str, ...], ...] = (
    ("hba1c",),
    ("ldl",),
    ("egfr", "creatinine", "cr"),
    ("hb", "hemoglobin"),
)


def _get_soap_template(ctx: NarrativeContext) -> Any | None:
    """Extract outpatient_soap_template.

    v9 (2026-08-17): resolution chain
      1. encounter_protocol.narrative.outpatient_soap_template
         (encounter-specific — screening / vaccination / referral etc.)
      2. disease_protocol.narrative.outpatient_soap_template
         (acute disease follow-up — v9 new layer)
      3. chronic_soap_templates.yaml lookup by primary chronic ICD
         (v9 new layer — closes the "chronic follow-up" gap for
         hypertension / DM / CKD / etc. which have no per-disease YAML)
      4. None → caller falls through to patient-state engine

    Issue #3249: a visit with a visit-reason kind (chemotherapy,
    post-discharge, acute illness, screening, vaccination, well-child) takes
    its content from ``visit_reason_soap.yaml`` instead (``kind_lines``), so
    no template applies; the chronic-condition template is the one of the
    visit's own diagnosis (the condition the follow-up is for), not of the
    patient's first chronic condition.
    """
    if visit_kind(ctx):
        return None
    ep = ctx.encounter_protocol
    if ep is not None:
        narrative = _o(ep, "narrative", None)
        if narrative is not None:
            tmpl = _o(narrative, "outpatient_soap_template", None)
            if tmpl is not None:
                return tmpl
    # L2: disease-side (acute follow-up)
    dp = ctx.disease_protocol
    if dp is not None:
        narrative = _o(dp, "narrative", None)
        if narrative is not None:
            tmpl = _o(narrative, "outpatient_soap_template", None)
            if tmpl is not None:
                return tmpl
    # L3: chronic-condition registry (v9 new)
    #
    # Session-98 log-noise fix: the registry (`chronic_soap_templates.yaml`)
    # only carries `_ja` fields today. On EN runs `_pick_localized` would
    # emit "template locale field subjective_en missing" and fall through
    # to the CIF-composed EN path anyway — 91,640 warnings on the p=10000
    # US sim, all no-op. Skip the registry entirely for EN so the
    # warning fires only when a genuinely bilingual template drops a
    # locale (the guardrail's original intent).
    if has_authored_narrative(ctx.target_lang):
        from clinosim.modules.document.narrative._chronic_soap import resolve_chronic_soap

        dx = visit_dx(ctx)
        patient = ctx.patient
        if dx:
            return resolve_chronic_soap([dx])
        if patient is not None:
            conds = _o(patient, "chronic_conditions", []) or []
            chronic_tmpl = resolve_chronic_soap(conds)
            if chronic_tmpl is not None:
                return chronic_tmpl
    return None


# ─────────────────────────────────────────────────────────────────────
# SUBJECTIVE
# ─────────────────────────────────────────────────────────────────────


@section("subjective")
def build_outpatient_subjective(generator: TemplateNarrativeGenerator, ctx: NarrativeContext) -> tuple[str, list[str]]:
    """Build SOAP subjective from outpatient_soap_template.subjective_<lang>.

    v9 (2026-08-17): dropped the single-line "特記事項なし" fallback in
    favour of a CIF-composed subjective line so Template-only output
    carries usable density. Resolution chain:
      1. encounter_protocol.narrative.outpatient_soap_template.subjective_<lang>
         (explicit encounter-YAML author intent — highest fidelity)
      2. compose from CIF: age/sex + encounter.chief_complaint +
         chronic-condition follow-up context
      3. generic "特記事項なし" only when CIF truly empty (patient=None)
    """
    facts: list[str] = []
    lang = ctx.target_lang
    fallback = t("fallback.generic_fallback", lang)

    # v9 (2026-08-17 evening) FIX: v11 review found 28 encounters had
    # identical stereotype subjective because the chronic SOAP
    # registry supplied a fixed template and the CIF-composed
    # per-patient content was skipped. Now: always append the
    # per-patient composition (age / sex / CC / chronic) even when
    # a template exists, so the reader sees encounter-specific
    # variation on top of the disease-class seed.
    composed = _compose_outpatient_subjective_from_state(ctx)
    # Issue #3249: the visit reason's own subjective lines.
    kind = visit_kind(ctx)
    reason_lines = kind_lines(ctx, kind, "subjective")
    if composed and reason_lines:
        composed = join_sentences([composed, *reason_lines], lang)
        facts.append("composed:visit_reason.subjective")
    # Issue #3407: the admissions and emergency visits since the previous visit
    # (a visit-reason kind states its own index admission).
    interval_line = "" if kind else interval_event_line(ctx)
    if interval_line:
        composed = join_sentences([composed, interval_line], lang) if composed else interval_line
        facts.append("ctx.interval_encounters")
    soap = _get_soap_template(ctx)
    template_prose = ""
    if soap is not None:
        if _o(soap, "subjective", None):
            template_prose = _pick_localized(soap, "subjective", lang, ctx)
            if template_prose == fallback:
                template_prose = ""
        if not interval_events(ctx) and _o(soap, "no_interval_event", None):
            no_event = _pick_localized(soap, "no_interval_event", lang, ctx)
            template_prose = join_sentences([template_prose, no_event], lang) if template_prose else no_event
    if composed and template_prose:
        facts.extend(
            [
                f"outpatient_soap_template.subjective_{lang}",
                "ctx.patient.demographics",
                "ctx.encounter.chief_complaint",
                "ctx.patient.chronic_conditions",
            ]
        )
        return f"{composed} {template_prose.strip()}", facts
    if composed:
        facts.extend(["ctx.patient.demographics", "ctx.encounter.chief_complaint", "ctx.patient.chronic_conditions"])
        return composed, facts
    if template_prose:
        facts.append(f"outpatient_soap_template.subjective_{lang}")
        return template_prose.strip(), facts

    return fallback, facts


def _compose_outpatient_subjective_from_state(ctx: NarrativeContext) -> str:
    """Compose a CIF-only SOAP subjective for outpatient visits.

    v9 (2026-08-17) density fix — Template-only output was
    "特記事項なし" for 100 % of outpatient encounters lacking an
    encounter-YAML template. This builds a clinically-readable
    subjective from age + sex + chief_complaint + chronic-context.
    All fields are CIF-CONFIRMED (patient profile + encounter
    record); no scenario data is asserted here.
    """
    patient = ctx.patient
    enc = ctx.encounter
    if patient is None:
        return ""
    lang = ctx.target_lang
    age = _age_at(ctx)
    sex_raw = _o(patient, "sex", None) or ""
    # Sex vocabulary moved to narrative_labels.yaml::sex_label
    # (Phase 1d-16). Case-insensitive lookup via _label's built-in
    # fallback path.
    sex_label = _label("sex_label", str(sex_raw).lower(), lang, fallback="")
    # chief_complaint — encounter first (v9 chief_complaint bug fix),
    # skip English-in-JA leak.
    cc = encounter_chief_complaint(ctx) if enc is not None else ""
    # Chronic condition follow-up context (code-lookup localized).
    # Issue #1333: route CIF base code through map_diagnosis_code so the
    # narrative display matches the FHIR emit-target (US F00 → F03.90
    # renders as "Unspecified dementia", not the WHO parent-code
    # "Dementia in Alzheimer disease").
    # Issue #3248: every condition, the visit's own problem first.
    country = country_code(ctx.locale)
    sex = str(_o(patient, "sex", "") or "")
    chronic_labels: list[str] = []
    for c in ordered_chronic_conditions(ctx):
        code = _o(c, "code", "") or (c if isinstance(c, str) else "")
        # Issue #2994: the label of the condition the output codes.
        disp = chronic_condition_label(code, country, lang, sex)
        # Issue #1777: when the display lookup misses, SKIP the entry
        # rather than leak the raw ICD code into narrative free text.
        # The prose sentence "Follow-up of chronic conditions: G47.30"
        # reads as a coding sheet, not a clinical note; a shorter list
        # with only resolvable items reads correctly.
        # Issue #3259: two conditions with one name are listed once.
        if not disp or disp in chronic_labels:
            continue
        chronic_labels.append(disp)
    # Compose
    parts: list[str] = []
    if age and sex_label:
        parts.append(t("outpatient.subject_with_sex", lang, age=age, sex=sex_label))
    elif age:
        parts.append(t("outpatient.subject_no_sex", lang, age=age))
    if cc:
        parts.append(t("outpatient.visit_reason_with_cc", lang, cc=cc))
    else:
        parts.append(t("outpatient.visit_reason_no_cc", lang))
    if chronic_labels and visit_kind(ctx):
        # Issue #3249: a visit made for another reason lists the chronic
        # problems as known conditions, not as the reason for the visit.
        parts.append(known_conditions_tail(chronic_labels, lang))
    elif chronic_labels:
        sep = t("list_sep.serial", lang)
        parts.append(t("outpatient.chronic_followup", lang, list=sep.join(chronic_labels)))
    text = "".join(parts).strip()
    return text


# ─────────────────────────────────────────────────────────────────────
# OBJECTIVE
# ─────────────────────────────────────────────────────────────────────


@section("objective")
def build_outpatient_objective(generator: TemplateNarrativeGenerator, ctx: NarrativeContext) -> tuple[str, list[str]]:
    """Build SOAP objective — CIF vitals ALWAYS appear; template is a seed.

    v9 (2026-08-17 evening) FIX: v11 review found 82% of outpatient
    objective sections were "特記事項なし" because the chronic SOAP
    registry supplied templates with `{vital_line}` placeholders that
    _pick_localized couldn't resolve, and the whole section fell back
    to the generic phrase. The registry has been simplified (no
    placeholders) and this builder now:
      1. Composes the CIF vitals line (BP/HR/RR/SpO2/T) as the primary content
      2. Appends the encounter/disease/chronic-registry template text
         as clinical context prose when available
      3. Falls back to vitals-only when no template exists
      4. Only returns the generic 「特記事項なし」 when BOTH template
         text AND vitals are absent (rare — every outpatient encounter
         records at least BP+HR)
    """
    facts: list[str] = []
    lang = ctx.target_lang
    fallback = t("fallback.generic_fallback", lang)

    vital_line = generator._compose_vital_signs_line(ctx)
    kind = visit_kind(ctx)
    values = kind_values(ctx, kind)
    reason_lines = kind_lines(ctx, kind, "objective", values)
    # Issue #3231: the flagged lab results and screening scores of the visit.
    results = _result_objective(ctx)
    if _result_objective(ctx, with_pending=False):
        facts.append("ctx.lab_results.today")
    if _pending_labs_text(ctx):
        facts.append("ctx.lab_results.pending")
    if reason_lines:
        # Issue #3249 / #3252: the visit reason's findings (growth, wound,
        # pre-treatment labs, screening results).
        facts.append("composed:visit_reason.objective")
        body = join_sentences([*reason_lines, *([results] if results else [])], lang)
        if vital_line:
            facts.append("ctx.vitals")
            return f"{vital_line}{t('list_sep.period_space', lang)}{body}", facts
        return body, facts
    template_prose = ""
    soap = _get_soap_template(ctx)
    if soap is not None:
        if _o(soap, "objective", None):
            template_prose = _pick_localized(soap, "objective", lang, ctx)
            if template_prose == fallback:
                # _fill_template_placeholders returned the fallback marker
                # (unresolvable placeholder); treat as empty so vitals alone
                # supply the section.
                template_prose = ""

    prose = template_prose.strip()
    if vital_line and prose:
        facts.extend(["ctx.vitals", "outpatient_soap_template.objective"])
        return join_sentences([vital_line, prose, results], lang), facts
    if vital_line:
        facts.append("ctx.vitals")
        return join_sentences([vital_line, results], lang), facts
    if prose:
        facts.append("outpatient_soap_template.objective")
        return join_sentences([prose, results], lang), facts
    if results:
        return results, facts
    return fallback, facts


# ─────────────────────────────────────────────────────────────────────
# ASSESSMENT
# ─────────────────────────────────────────────────────────────────────


@section("assessment")
def build_outpatient_assessment(generator: TemplateNarrativeGenerator, ctx: NarrativeContext) -> tuple[str, list[str]]:
    """Build SOAP assessment from outpatient_soap_template.assessment_<lang>.

    Also handles ED_NOTE context (falls back to CIF-composed assessment).

    Issue #780: when no template is available, list active chronic conditions
    so the A section reflects the patient's real problem list.

    Issue #1074 B9 (session-99 2026-09-04): ED_NOTE and outpatient-with-no-
    chronic-conditions paths now compose from CIF facts (primary dx +
    working diagnoses / chief complaint) instead of the generic
    ``Clinical assessment ongoing`` fallback.
    """
    facts: list[str] = []
    lang = ctx.target_lang
    fallback = t("fallback.generic_assessment", lang)

    # ED_NOTE: previously returned generic. Now composes from CIF —
    # primary dx code + working diagnoses give a per-patient A line.
    if ctx.document_type == DocumentType.ED_NOTE:
        composed = _compose_ed_assessment_from_state(ctx)
        if composed:
            facts.append("ctx.ed_assessment.state_composed")
            return composed, facts
        return fallback, facts

    # Issue #985: ALWAYS compute the integrated per-chronic-condition
    # value block first, so an encounter YAML template ("HbA1c 目標
    # 7.0% 未満を基準に評価") gets an appended CIF-anchored value line
    # ("1. 2型糖尿病: HbA1c 6.8% — 目標 7.0% 未満 — 目標達成中"),
    # rather than emitting identically for 100+ diabetic patients.
    integrated = _compose_chronic_assessment_integrated(ctx)

    # Issue #3249: the reason for the visit (and the vaccines given at it) is
    # the first item; the chronic problems and the vital-sign findings follow.
    # The problem a visit-reason item covers (the cancer of a chemotherapy
    # visit) is not listed again.
    kind = visit_kind(ctx)
    reason_items = kind_lines(ctx, kind, "assessment")
    if reason_items:
        facts.append("composed:visit_reason.assessment")
        integrated = _numbered(reason_items + _chronic_assessment_items(ctx, skip_code=visit_dx(ctx) if kind else ""))

    soap = _get_soap_template(ctx)
    if soap is not None:
        text = _pick_localized(soap, "assessment", lang, ctx)
        if text:
            facts.append(f"encounter_protocol.narrative.outpatient_soap_template.assessment_{lang}")
            if integrated:
                facts.extend(["ctx.patient.chronic_conditions", "ctx.vitals.today", "ctx.lab_results.today"])
                return f"{text}\n{integrated}", facts
            return text, facts

    # v9 (2026-08-17) density fix: build a per-chronic-condition
    # assessment line that integrates today's vitals + abnormal labs,
    # not just a raw code list. Falls back to the flat chronic list
    # when no interpretation is available.
    if integrated:
        facts.extend(["ctx.patient.chronic_conditions", "ctx.vitals.today", "ctx.lab_results.today"])
        return integrated, facts

    # Original #780 fallback (chronic list only)
    chronic_line = _compose_chronic_condition_line(ctx)
    if chronic_line:
        facts.append("ctx.patient.chronic_conditions")
        return chronic_line, facts

    # Issue #1074 B9: patients with NO chronic conditions previously fell
    # through to the generic "Clinical assessment ongoing" — 11.6 % of
    # 1,409 progress notes in the US p=2000 seed=500 baseline. When no
    # template + no chronic list is available, compose from the primary
    # encounter reason (chief_complaint + primary_dx_display) so the
    # assessment reflects the actual visit.
    cc_line = _compose_encounter_reason_line(ctx)
    if cc_line:
        facts.append("ctx.encounter.chief_complaint")
        return cc_line, facts

    return fallback, facts


def _compose_ed_assessment_from_state(ctx: NarrativeContext) -> str:
    """ED_NOTE assessment composed from CIF facts (Issue #1074 B9).

    Combines admission dx + working diagnoses + primary complications
    into a short JA/EN line so ED encounters carry per-patient A text.
    Empty string when no facts available (caller falls back to generic).
    """
    lang = ctx.target_lang

    # Use working_diagnoses from ctx if available
    wds = list(getattr(ctx, "working_diagnoses", []) or [])
    primary_dx_codes: list[str] = []
    for wd in wds[:3]:
        if isinstance(wd, dict):
            code = wd.get("disease_id") or wd.get("code") or wd.get("icd_code")
            if code:
                primary_dx_codes.append(str(code))
        else:
            code = _o(wd, "disease_id", None) or _o(wd, "code", None)
            if code:
                primary_dx_codes.append(str(code))

    # If no working dx, fall back to encounter chief complaint anchor
    parts: list[str] = []
    if primary_dx_codes:
        disp_key = _label("code_system_icd_display", "primary", lang)
        country = country_code(ctx.locale)
        labels: list[str] = []
        for code in primary_dx_codes:
            # Issue #3259: the prose name of the code the output emits; a
            # non-ICD key falls back to the registry display, then the key.
            disp = chronic_condition_label(code, country, lang) or registry_display(disp_key, code, lang) or code
            if disp not in labels:
                labels.append(disp)
        sep = t("list_sep.serial", lang)
        parts.append(t("ed_assessment.working_dx_line", lang, list=sep.join(labels)))
    else:
        # Fall through to chief_complaint if no dx
        cc = _compose_encounter_reason_line(ctx)
        if cc:
            return cc

    # Complications if any.
    # Phase 1c-2 (2026-09-22): localize complication tokens (6 leaks
    # in JP p=500 ed assessment audit — "合併症: acute_kidney_injury"
    # → "合併症: 急性腎障害").
    comps = list(getattr(ctx, "complications_occurred", []) or [])
    if comps:
        comp_labels = [_localize_complication(str(c), lang) for c in comps[:3]]
        sep = t("list_sep.serial", lang)
        parts.append(t("ed_assessment.complications_line", lang, list=sep.join(comp_labels)))

    sep = t("list_sep.period_space", lang)
    return sep.join(parts) + (t("list_sep.period", lang) if parts else "")


def _compose_encounter_reason_line(ctx: NarrativeContext) -> str:
    """Short JA/EN line describing the visit's primary reason (Issue #1074 B9).

    Reads ``encounter.chief_complaint`` first; falls back to
    ``primary_diagnosis`` when the CC is empty or looks like a template
    stub. Empty string when neither is available.
    """
    enc = getattr(ctx, "encounter", None)
    if enc is None:
        return ""
    # Phase 1c-6 (2026-09-23): prefer the locale-specific
    # ``chief_complaint_{ja,en}`` over the raw ``chief_complaint``
    # so JA output emits 「来院理由: 予防接種」 rather than the
    # underlying-EN 「来院理由: Vaccination visit」 for encounters
    # (immunization / vaccination visits, ED follow-ups) whose
    # emitters populate both language slots. Mirrors the pattern in
    # `_render_outpatient_chronic_soap` (line 5258).
    cc = encounter_chief_complaint(ctx).strip()
    primary_dx = _o(enc, "primary_diagnosis", "") or _o(enc, "primary_dx", "") or ""
    primary_dx = str(primary_dx).strip()

    # Prefer a non-empty, non-stub chief_complaint. Phase 1d-4
    # (2026-09-23): binary ``if is_ja: X else Y`` inline templates
    # replaced with the language-agnostic ``t(key, lang, **params)``
    # phrase-catalog lookup (see ``clinosim/locale/i18n.py`` and
    # ``narrative_phrases.yaml``). Adding fr / zh / … requires only
    # a YAML edit; no code change here.

    if cc and cc.lower() not in ("none", "n/a", "--"):
        return t("chief_complaint.encounter_reason", ctx.target_lang, cc=cc)
    if primary_dx:
        return t("chief_complaint.primary_problem", ctx.target_lang, dx=primary_dx)
    return ""


def _compose_chronic_condition_line(ctx: NarrativeContext) -> str:
    """List the patient's active chronic conditions in a short JA/EN line
    for the SOAP Assessment section (Issue #780 fallback)."""
    patient = ctx.patient
    conditions = _o(patient, "chronic_conditions", []) or []
    if not conditions:
        return ""
    # Resolve each condition to a language-appropriate label. `code` is
    # ICD-10 (JP) or ICD-10-CM (US) — use the shared codes registry to
    # pick a JA display when available; fall back to the code itself.

    lang = ctx.target_lang
    country = country_code(ctx.locale)
    sex = str(_o(patient, "sex", "") or "")
    labels: list[str] = []
    for c in ordered_chronic_conditions(ctx):
        code = _o(c, "code", "") or (c if isinstance(c, str) else "")
        # Issue #2994: the label of the condition the output codes.
        label = chronic_condition_label(code, country, lang, sex) or code
        # Issue #3259: two conditions with one name are listed once.
        if label not in labels:
            labels.append(label)
    if not labels:
        return ""
    sep = t("list_sep.serial", lang)
    return t("chronic.followup_head", lang, list=sep.join(labels))


def _compose_chronic_assessment_integrated(ctx: NarrativeContext) -> str:
    """The numbered chronic-condition and vital-sign items of the SOAP
    Assessment (``_chronic_assessment_items``)."""
    return _numbered(_chronic_assessment_items(ctx))


def _numbered(items: list[str]) -> str:
    """Issue #3248: the items are numbered once, at the end, so a staged
    problem, a skipped entry and the vital-sign items cannot leave a gap."""
    return "\n".join(f"{n}. {item}" for n, item in enumerate(items, 1))


def _chronic_assessment_items(ctx: NarrativeContext, skip_code: str = "") -> list[str]:
    """The Assessment items of the chronic problems (``_chronic_assessment``),
    then the visit's abnormal results and screening scores (Issue #3231) and
    its abnormal vital signs (Issue #1183)."""
    items = _chronic_assessment(ctx, skip_code).items
    items.extend(finding for finding, _plan in _visit_result_findings(ctx))
    # Issue #1183: an abnormal vital sign surfaces in the Assessment whatever
    # the chronic-condition list. Issue #3251: as a finding linked to the
    # known diagnosis, with the matching plan line (``_visit_vital_findings``).
    items.extend(finding for finding, _plan in _visit_vital_findings(ctx))
    return items


@dataclass
class _ChronicAssessment:
    """The per-problem Assessment items, the lab names they cite (lowercase)
    and the plan lines the judgements call for."""

    items: list[str] = field(default_factory=list)
    cited: set[str] = field(default_factory=set)
    plans: list[str] = field(default_factory=list)


def _chronic_assessment(ctx: NarrativeContext, skip_code: str = "") -> _ChronicAssessment:
    """SOAP Assessment enriched with today's vitals + labs + target
    comparison prose (Issue #985 personalization).

    v9 emitted a chronic-condition list; v9-density integrated abnormal
    labs but only fired on ``flag`` presence and lacked target-reference
    prose. #985 lifts:

      - Cites the patient's actual value regardless of flag (a
        controlled HbA1c 6.8% is still worth citing against target
        7.0% — that's the point of the follow-up assessment).
      - Adds explicit target reference (JDS DM HbA1c < 7.0%, JAS
        LDL by JAS 2022 risk tier (Issue #2942), the patient's one JSH BP
        target (130/80 or 140/90 by age and comorbidity, Issue #3021),
        KDIGO CKD stage classification).
      - Adds CKD staging from eGFR when present.
      - Adds pertinent negatives (尿アルブミン when measured) so the
        assessment reads as "actively assessed and negative" rather
        than silent.
      - Adds continuation-med tail for the primary chronic drug when
        present in ``current_medications``.

    All values are CIF-CONFIRMED (measured today or carried from
    ``current_medications``). Never fabricates a "前回" prior value —
    outpatient chronic-care follow-ups have single-visit lab scope in
    this simulator; a prior-visit comparison would need cross-encounter
    history that ctx does not currently carry. The generic follow-up
    stub falls through when no measurement is available.
    """
    patient = ctx.patient
    out = _ChronicAssessment()
    if patient is None:
        return out
    conditions = _o(patient, "chronic_conditions", []) or []
    # Issue #1183: the empty-conditions early return silently dropped
    # abnormal-vital lines for patients with no chronic conditions.
    # Continue into the loop with an empty condition list; the
    # vital-abnormal pass at the end still fires.
    vitals = list(ctx.vitals or [])
    labs = known_labs(ctx)
    v0 = vitals[0] if vitals else None
    sbp = _o(v0, "systolic_bp", None) if v0 else None
    dbp = _o(v0, "diastolic_bp", None) if v0 else None

    # Issue #985: cite value regardless of flag — a target-comparison
    # assessment needs the actual number even when in-range.
    lab_by_name: dict[str, tuple[Any, str | None]] = {}
    for lab in labs:
        name = str(_o(lab, "lab_name", "") or "").lower()
        val = _o(lab, "value", None)
        if not name or val is None:
            continue
        lab_by_name[name] = (val, _o(lab, "unit", None))
    # Issue #3273: an analyte the visit did not measure is cited from the
    # latest earlier result (with its date) rather than from the stage stored
    # on the problem list. A group (renal function, blood count) is taken
    # whole from one source, never mixed.
    measured_on: dict[str, str] = {}
    for _group in _LAB_GROUPS:
        if any(n in lab_by_name for n in _group):
            continue
        _prior = prior_lab_values(ctx)
        _have = [n for n in _group if n in _prior]
        if _have:
            _pick = _have[0]
            lab_by_name[_pick] = (_prior[_pick][0], _prior[_pick][1])
            measured_on[_pick] = _prior[_pick][2]

    def _when(*names: str) -> str:
        """`` (measured YYYY-MM-DD)`` for the first of ``names`` taken from an
        earlier visit, else empty."""
        for n in names:
            if n in measured_on:
                return t("outpatient_results.measured_on", ctx.target_lang, date=measured_on[n])
        return ""

    lang = ctx.target_lang
    _sex = str(_o(patient, "sex", "") or "")

    # Pre-resolve current-medications for continuation-tail. Issue #1033:
    # rendering always as ``lang="ja"`` leaks katakana drug names into US
    # assessment prose (`Metformin continue` → `メトホルミン continue`).
    # Render in the target locale and match hints in the target locale so
    # a US assessment cites the English drug name and a JP assessment
    # cites the katakana name.
    # Issue #3250 / #3262: the medications at the start of the visit.
    cur_meds = home_medications_at_admission(ctx)[0]
    med_rows = [m for m in cur_meds if _render_home_med_name(m, lang=ctx.target_lang)]
    med_names_display = [_render_home_med_name(m, lang=ctx.target_lang) for m in med_rows]

    def _pick_med_by_class(class_key: str) -> str | None:
        """Every current medication of a chronic-condition class, joined
        (Issue #3250: all the drugs of the class, not the first): a name
        containing a hint of ``chronic-med-class-hints.yaml`` (in the output
        language) or a drug of the class's catalog drug classes."""
        hints = _chronic_med_class_hints(class_key, lang)
        classes = tuple(_chronic_med_class_hints_raw().get(class_key, {}).get("drug_classes") or ())
        picked = [
            n
            for n, m in zip(med_names_display, med_rows, strict=True)
            if any(h in n for h in hints) or (classes and medication_matches(m, classes=classes))
        ]
        return t("list_sep.serial", lang).join(picked) if picked else None

    items = out.items
    # Issue #3259: a problem is listed once (two codes with one name — I80
    # and I82 deep-vein thrombosis — are one item), and the diabetes control
    # judgement (HbA1c, glucose, medication) is written once, on the first
    # diabetes item; a complication item (E11.311 retinopathy) is listed
    # under its own name like any other problem.
    listed: set[str] = set()
    # Issue #3249: the problem a visit-reason item already covers (the cancer
    # of a chemotherapy visit) is not listed again.
    if skip_code:
        listed.add(chronic_condition_label(skip_code, country_code(ctx.locale), ctx.target_lang, _sex) or skip_code)
    diabetes_judged = False
    for c in ordered_chronic_conditions(ctx):
        _dm_judged_before = diabetes_judged
        code = _o(c, "code", "") or (c if isinstance(c, str) else "")
        # Issue #2994: the label of the condition the output codes.
        label = chronic_condition_label(code, country_code(ctx.locale), ctx.target_lang, _sex) or code
        if label in listed:
            continue
        listed.add(label)
        code_prefix = code.split(".")[0].upper()
        interp = ""

        # ── I10: Essential hypertension ────────────────────────────
        if code_prefix.startswith("I10") and sbp and dbp:
            # Issue #3021: one target for the patient (age, comorbidities),
            # stated and used for the control judgement.
            _bp_target = bp_target(ctx.locale, _age_at(ctx), [str(_o(cc, "code", "") or cc) for cc in conditions])
            ctrl = t(
                {
                    "hypertension": "control_status.poorly_controlled",
                    "above_target": "control_status.high_normal",
                    "at_goal": "control_status.at_goal",
                }[bp_control(float(sbp), float(dbp), _bp_target, ctx.locale)],
                lang,
            )
            target = t(
                "chronic_assessment.bp_target",
                lang,
                sbp=_bp_target[0],
                dbp=_bp_target[1],
            )
            med = _pick_med_by_class("hypertension")
            med_tail = t("chronic_assessment.med_continue_tail", lang, med=med) if med else ""
            interp = f"BP {int(sbp)}/{int(dbp)} mmHg — {target} — {ctrl}{med_tail}" + t("list_sep.period", lang)
            # Issue #3250: a reading above target calls for a plan action.
            if bp_control(float(sbp), float(dbp), _bp_target, ctx.locale) != "at_goal":
                out.plans.append(t("outpatient_results.plan_bp_above_target", lang))

        # ── E11 / E10: Diabetes mellitus ───────────────────────────
        elif concept_group("diabetes").contains(code_prefix) and not diabetes_judged:
            diabetes_judged = True
            parts_dm: list[str] = []
            hba1c = lab_by_name.get("hba1c")
            if hba1c:
                v, u = hba1c
                try:
                    vf = float(v)
                    if vf >= NARRATIVE_HBA1C_DIABETES_THRESHOLD + 0.5:  # ≥ 7.0
                        ctrl = t("control_status.poorly_controlled", lang)
                    elif vf >= NARRATIVE_HBA1C_DIABETES_THRESHOLD:  # 6.5-7.0
                        ctrl = t("control_status.near_target", lang)
                    else:
                        ctrl = t("control_status.at_goal_active", lang)
                except (TypeError, ValueError):
                    ctrl = ""
                target = t("control_status.hba1c_target_below_7", lang)
                out.cited.add("hba1c")
                _hb = f"HbA1c {v}{u or '%'}{_when('hba1c')}"
                parts_dm.append(f"{_hb} — {target} — {ctrl}" if ctrl else f"{_hb} — {target}")
            # 尿アルブミン (pertinent info when measured)
            ualb = lab_by_name.get("urine_albumin") or lab_by_name.get("albuminuria")
            if ualb:
                v, u = ualb
                out.cited.update(("urine_albumin", "albuminuria"))
                parts_dm.append(t("chronic_labs.urine_albumin", lang, value=v, unit=u or "mg/gCr"))
            # 空腹時血糖 — Issue #1188 F4: Nathan formula consistency
            # gate. `eAG (mg/dL) ≈ 28.7 × HbA1c − 46.7`. When HbA1c is
            # elevated (≥8) but the glucose is normoglycemic (<160),
            # the paired citation is clinically implausible (a random
            # glucose of 120-135 mg/dL is not compatible with HbA1c 9%
            # unless the sample is a rare tight-fasting draw). Rather
            # than paper over the underlying CIF sampling mismatch,
            # skip the glucose citation when the pair is Nathan-
            # inconsistent — HbA1c is the more meaningful long-term
            # marker anyway, and the Assessment line stays clean.
            fbg = lab_by_name.get("glucose")
            if fbg:
                v_g, u_g = fbg
                _emit_glucose = True
                if hba1c:
                    try:
                        _hba1c_val = float(hba1c[0])
                        _glucose_val = float(v_g)
                        _expected_eag = 28.7 * _hba1c_val - 46.7
                        # Skip when reported glucose is >60 mg/dL below
                        # the Nathan-expected eAG (i.e., the pair
                        # implausibly asserts good acute control on a
                        # patient with poor long-term control).
                        if _hba1c_val >= 8.0 and _glucose_val + 60 < _expected_eag:
                            _emit_glucose = False
                    except (TypeError, ValueError):
                        pass
                if _emit_glucose:
                    out.cited.add("glucose")
                    parts_dm.append(t("chronic_labs.glucose_line", lang, value=v_g, unit=u_g or "mg/dL"))
            med = _pick_med_by_class("diabetes")
            if med:
                parts_dm.append(t("prescription.medication_continue", lang, med=med))
            if parts_dm:
                interp = t("list_sep.serial", lang).join(parts_dm) + t("list_sep.period", lang)

        # ── E78: Dyslipidemia ──────────────────────────────────────
        elif code_prefix.startswith("E78"):
            ldl = lab_by_name.get("ldl")
            _ldl = chronic_control_targets(ctx.locale).ldl
            # Issue #2942: the stated target is the patient's risk-tier
            # target, the threshold the statin titration uses
            # (statin_monitoring.ldl_target); none in the US, whose
            # guideline sets no LDL target.
            _target = statin_ldl_target(SimpleNamespace(chronic_conditions=conditions), ctx.locale)
            # Issue #3272: without a target (the US) the LDL is judged against
            # the patient's risk-based decision threshold, never called "at
            # goal" against a band that is not a goal.
            _threshold = statin_ldl_risk_threshold(SimpleNamespace(chronic_conditions=conditions), ctx.locale)
            if ldl:
                v, u = ldl
                out.cited.add("ldl")
                try:
                    vf = float(v)
                    if _target is None and _threshold is not None:
                        _side = "above" if vf >= _threshold[0] else "below"
                        _variant = _ldl_threshold_variant(ctx, cur_meds) if _side == "above" else ""
                        ctrl = t(
                            f"chronic_assessment.ldl_threshold_{_side}_{_threshold[1]}{_variant}",
                            lang,
                            ldl=f"{_threshold[0]:g}",
                        )
                    elif vf >= _ldl.high:
                        ctrl = t("control_status.high_ldl_statin_underresponse", lang)
                    elif vf >= _ldl.borderline:
                        ctrl = t("control_status.borderline_intensification", lang)
                    elif vf >= (_target[0] if _target is not None else _ldl.elevated):
                        ctrl = t("control_status.elevated", lang)
                    else:
                        ctrl = t("control_status.at_goal", lang)
                except (TypeError, ValueError):
                    ctrl = ""
                target_part = (
                    t(f"chronic_assessment.ldl_target_{_target[1]}", lang, ldl=f"{_target[0]:g}") + " — "
                    if _target is not None
                    else ""
                )
                med = _pick_med_by_class("dyslipidemia")
                med_tail = t("chronic_assessment.med_continue_tail", lang, med=med) if med else ""
                interp = f"LDL {v} {u or 'mg/dL'}{_when('ldl')} — {target_part}{ctrl}{med_tail}" + t(
                    "list_sep.period", lang
                )

        # ── N18: Chronic kidney disease ────────────────────────────
        elif code_prefix.startswith("N18"):
            parts_ckd: list[str] = []
            cr = lab_by_name.get("cr") or lab_by_name.get("creatinine")
            egfr = lab_by_name.get("egfr")
            if egfr:
                v, u = egfr
                try:
                    stage = ckd_g_stage(float(v))
                except (TypeError, ValueError):
                    stage = ""
                stage_ja = t("chronic_labs.ckd_stage", lang, stage=stage)
                # UCUM eGFR unit "mL/min/{1.73_m2}" carries a `{}`
                # annotation that reads as a placeholder in narrative.
                # Prefer the plain human display for prose emit.
                display_u = "mL/min/1.73m²" if u and "1.73" in str(u) else (u or "mL/min/1.73m²")
                out.cited.update(("egfr", "creatinine", "cr"))
                parts_ckd.append(f"eGFR {v} {display_u}{_when('egfr')} ({stage_ja})")
            if cr and not egfr:
                v, u = cr
                out.cited.update(("creatinine", "cr"))
                parts_ckd.append(f"Cr {v} {u or 'mg/dL'}{_when('creatinine', 'cr')}")
            if parts_ckd:
                interp = t("list_sep.serial", lang).join(parts_ckd) + (t("chronic_monitoring.renal_function", lang))

        # ── I48: Atrial fibrillation / flutter ─────────────────────
        # Anticoagulation is the primary monitoring axis. INR is the
        # therapeutic marker for warfarin only (2.0-3.0 for non-valvular
        # AFib per ACC/AHA + JCS guidelines). A DOAC is not monitored by
        # INR: its follow-up reviews renal function, the blood count and
        # bleeding (Issue #2993; 2023 ACC/AHA/ACCP/HRS AF guideline, 2021
        # EHRA practical guide). The med-continuation tail records the drug.
        elif code_prefix.startswith("I48"):
            parts_afib: list[str] = []
            on_warfarin = any(medication_matches(m, classes=("anticoagulant.vka",)) for m in cur_meds)
            on_doac = any(medication_matches(m, classes=("anticoagulant.doac",)) for m in cur_meds)
            inr = lab_by_name.get("pt-inr") or lab_by_name.get("pt_inr") or lab_by_name.get("inr")
            if inr and on_warfarin:
                v, u = inr
                try:
                    vf = float(v)
                    if 2.0 <= vf <= 3.0:
                        ctrl = t("control_status.inr_therapeutic", lang)
                    elif vf < 2.0:
                        ctrl = t("control_status.inr_subtherapeutic", lang)
                    else:
                        ctrl = t("control_status.inr_supratherapeutic", lang)
                except (TypeError, ValueError):
                    ctrl = ""
                target = t("chronic_assessment.inr_target_standard", lang)
                parts_afib.append(f"PT-INR {v} — {target} — {ctrl}" if ctrl else f"PT-INR {v} — {target}")
            elif on_doac:
                parts_afib.extend(_doac_monitoring_values(lab_by_name, measured_on, lang))
                out.cited.update(("egfr", "creatinine", "cr", "hb", "hemoglobin"))
                # Issue #3231: the renal review is stated only when a renal
                # result is available; otherwise the plan orders it.
                if any(n in lab_by_name for n in ("egfr", "creatinine", "cr")):
                    parts_afib.append(t("chronic_assessment.doac_renal_bleeding_review", lang))
                else:
                    parts_afib.append(t("chronic_assessment.doac_renal_to_check", lang))
                    out.plans.append(t("outpatient_results.plan_doac_renal_check", lang))
            med = _pick_med_by_class("afib_anticoagulation")
            if med:
                parts_afib.append(t("prescription.medication_continue", lang, med=med))
            if parts_afib:
                interp = t("list_sep.serial", lang).join(parts_afib) + t("list_sep.period", lang)

        # ── J44: COPD (stable) ─────────────────────────────────────
        elif code_prefix.startswith("J44"):
            spo2 = _o(v0, "spo2", None) if v0 else None
            bits: list[str] = []
            if spo2:
                bits.append(f"SpO2 {float(spo2):.0f}%")
            med = _pick_med_by_class("copd")
            if med:
                bits.append(t("prescription.medication_inhalation_continue", lang, med=med))
            if bits:
                interp = t("list_sep.serial", lang).join(bits) + (t("chronic_monitoring.cat_mmrc_review", lang))

        # ── J45: Asthma ────────────────────────────────────────────
        elif code_prefix.startswith("J45"):
            spo2 = _o(v0, "spo2", None) if v0 else None
            bits2: list[str] = []
            if spo2:
                bits2.append(f"SpO2 {float(spo2):.0f}%")
            med = _pick_med_by_class("asthma")
            if med:
                bits2.append(t("prescription.medication_continue", lang, med=med))
            if bits2:
                interp = t("list_sep.serial", lang).join(bits2) + t(_asthma_control_phrase_key(_age_at(ctx)), lang)

        if interp:
            items.append(f"{label}: {interp}")
        else:
            # Issue #1776: the pre-fix fallback re-cited Objective-
            # section vitals (BP / HR / T / SpO2) and emitted a
            # "today's measurements not condition-specific; defer
            # focused review" clause that admitted no clinical
            # reasoning fired. That phrase saturated 74% of
            # populated narratives (197k / 263k on US p=10k seed=42
            # 5y) and taught downstream LLMs a procrastination
            # pattern. Replace with a structured-data fallback that
            # reads the chronic condition's ``stage`` (populated by
            # the longitudinal engine as of #1753): staged → cite
            # the stage; stageless → acknowledge the problem-list
            # entry with no acute change. Neither phrase re-quotes
            # the vitals and neither defers the judgement.
            condition_stage = str(_o(c, "stage", "") or "").strip()
            # Issue #3396: a stage restated from a result reported after the
            # note was authored is not known to it.
            if condition_stage and stage_from_pending_lab(ctx, str(code), condition_stage):
                condition_stage = ""
            # Issue #3259 / #3273: a diabetic complication's stored stage is an
            # HbA1c, the diabetes' own staging, not the complication's: omitted.
            if (
                _dm_judged_before
                and concept_group("diabetes").contains(code_prefix)
                and _HBA1C_IN_STAGE.search(condition_stage)
            ):
                condition_stage = ""
            if condition_stage:
                # Issue #3253: a condition followed for a drug class the
                # patient does not take is not "management continued".
                _fu = load_chronic_followup()
                _fu_spec = _fu.get(code) or _fu.get(code.split(".")[0]) or {}
                _med_class = _fu_spec.get("medication_class") if isinstance(_fu_spec, dict) else None
                _untreated = bool(_med_class) and not any(
                    medication_matches(m, classes=(_med_class,)) for m in cur_meds
                )
                follow = t(
                    "chronic_assessment.chronic_stage_untreated"
                    if _untreated
                    else (
                        "chronic_assessment.chronic_stage_above_target"
                        if _stage_hba1c_above_target(condition_stage)
                        else "chronic_assessment.chronic_stage_stable"
                    ),
                    lang,
                    label=label,
                    # Issue #3034: the stage label in the output language.
                    stage=_localize_stage(condition_stage, lang),
                )
                items.append(follow)
            else:
                items.append(t("chronic_assessment.chronic_noted", lang, label=label))

    return out


_HBA1C_IN_STAGE = re.compile(r"HbA1c\s*([0-9]+(?:\.[0-9]+)?)")


def _stage_hba1c_above_target(stage: str) -> bool:
    """Whether a stored stage text is an HbA1c at or above the target of the
    diabetes control judgement (Issue #3273): such a stage is not "no acute
    change"."""
    m = _HBA1C_IN_STAGE.search(stage)
    return m is not None and float(m.group(1)) >= NARRATIVE_HBA1C_DIABETES_THRESHOLD + 0.5


def _result_lab_entries(ctx: NarrativeContext, *, uncited_only: bool) -> list[str]:
    """The visit's flagged lab results worded as in the inpatient notes
    (``_notable_labs``), at most ``max_items.note`` and a count of the rest;
    with ``uncited_only`` the analytes the chronic-problem items already cite
    are left out (Issue #3231)."""
    from clinosim.modules.document.narrative._narrative_interpretation_thresholds import notable_lab_rules
    from clinosim.modules.document.narrative._notable_labs import notable_lab_entries

    labs = known_labs(ctx)
    if uncited_only:
        cited = _chronic_assessment(ctx).cited
        labs = [lab for lab in labs if str(_o(lab, "lab_name", "") or "").lower() not in cited]
    return notable_lab_entries(labs, None, None, ctx.target_lang, limit=notable_lab_rules().max_items.note)


def _score_text(name: str, value: float, positive: bool, lang: str) -> str:
    text = f"{name} {value:g}"
    return f"{text} {t('outpatient_results.positive_screen', lang)}" if positive else text


def _visit_result_findings(ctx: NarrativeContext) -> list[tuple[str, str]]:
    """``(assessment item, plan line)`` for the visit's results that no
    chronic-problem item cites (Issue #3231): the flagged lab results, and the
    screening scores (a positive screen with its follow-up plan)."""
    lang = ctx.target_lang
    out: list[tuple[str, str]] = []
    # A screening visit's own Assessment already lists its abnormal results.
    entries = [] if visit_kind(ctx) == "screening" else _result_lab_entries(ctx, uncited_only=True)
    if entries:
        out.append(
            (
                t("outpatient_results.abnormal_labs", lang, list=t("list_sep.semicolon", lang).join(entries)),
                t("outpatient_results.plan_abnormal_labs", lang),
            )
        )
    scores = screening_scores(known_labs(ctx))
    if scores:
        text = t("list_sep.serial", lang).join(_score_text(n, v, f is not None, lang) for n, v, f in scores)
        follow_ups = [t(f"outpatient_results.follow_up_{f}", lang) for _n, _v, f in scores if f]
        out.append((t("outpatient_results.screening_scores", lang, list=text), "\n".join(follow_ups)))
    return out


def _result_objective(ctx: NarrativeContext, *, with_pending: bool = True) -> str:
    """The Objective sentence(s) of the visit's flagged lab results and
    screening scores (Issue #3231); empty when it has none."""
    lang = ctx.target_lang
    parts: list[str] = []
    entries = _result_lab_entries(ctx, uncited_only=False)
    if entries:
        parts.append(t("outpatient_results.objective_labs", lang, list=t("list_sep.semicolon", lang).join(entries)))
    scores = screening_scores(known_labs(ctx))
    if scores:
        text = t("list_sep.serial", lang).join(_score_text(n, v, f is not None, lang) for n, v, f in scores)
        parts.append(t("outpatient_results.objective_scores", lang, list=text))
    pending = _pending_labs_text(ctx) if with_pending else ""
    if pending:
        parts.append(t("outpatient_results.objective_pending", lang, list=pending))
    return join_sentences(parts, lang) if parts else ""


def _pending_labs_text(ctx: NarrativeContext) -> str:
    """The tests drawn at the visit whose results are reported after the note
    was authored, worded as pending (Issue #3396); empty when none."""
    lang = ctx.target_lang
    names = pending_lab_names(ctx)
    limit = outpatient_results().pending_lab_limit
    shown = [*names[:limit]]
    if len(names) > limit:
        shown.append(t("outpatient_results.pending_more", lang, count=len(names) - limit))
    return t("list_sep.serial", lang).join(shown)


def _visit_vital_findings(ctx: NarrativeContext) -> list[tuple[str, str]]:
    """``(assessment item, plan line)`` of each abnormal vital sign of the
    visit's first vital set (``_visit_reason.vital_findings``). Issue #2986:
    a child's heart rate is judged against the normal range for the age."""
    vitals = list(ctx.vitals or [])
    v0 = vitals[0] if vitals else None
    if v0 is None or ctx.patient is None:
        return []

    def _float(name: str) -> float | None:
        raw = _o(v0, name, None)
        try:
            return float(raw) if raw is not None else None
        except (TypeError, ValueError):
            return None

    hr = _float("heart_rate")
    tachycardic = hr is not None and _is_tachycardic(hr, ctx.patient, v0, ctx)
    # Issue #3546: the medications of the visit (the list at its start and
    # today's prescription) decide whether the plan may speak of a rate-control
    # step-up.
    meds = [*home_medications_at_admission(ctx)[0], *(getattr(ctx, "discharge_medications", None) or [])]
    return vital_findings(
        ctx,
        hr,
        _float("temperature_celsius"),
        _float("spo2"),
        tachycardic,
        medications=meds,
        rx_unchanged=_prescription_unchanged(ctx),
    )


def _prescription_unchanged(ctx: NarrativeContext) -> bool:
    """Whether the visit leaves the medications as they were at its start (no
    prescription issued, or one without a difference)."""
    line = _compose_medication_changes_line(ctx)
    return not line or line == t("outpatient_results.med_unchanged", ctx.target_lang)


def _statin_action_recorded(ctx: NarrativeContext) -> bool:
    """Whether the visit records a lipid-lowering step: the statin stepped up
    (Issue #2877) or the non-statin add-on started (Issue #2942)."""
    if _compose_statin_titration_line(ctx):
        return True
    add_on = statin_monitoring_rules().add_on
    at_start = {_med_key(m) for m in home_medications_at_admission(ctx)[0]}
    return any(
        medication_matches(m, drugs=(add_on,)) and _med_key(m) not in at_start
        for m in (getattr(ctx, "discharge_medications", None) or [])
    )


def _ldl_threshold_variant(ctx: NarrativeContext, cur_meds: list[Any]) -> str:
    """Suffix of the ``ldl_threshold_above_<basis>`` phrase (Issue #3546): the
    advice follows the statin the patient is on (maximal statin: a non-statin
    add-on, not "intensification"; already on the add-on: further review) and
    words an advice the visit does not act on as a recommendation for review."""
    patient = SimpleNamespace(
        current_medications=[SimpleNamespace(**m) if isinstance(m, dict) else m for m in cur_meds]
    )
    acted = _statin_action_recorded(ctx)
    if on_maximal_statin(patient, ctx.locale):
        if any(medication_matches(m, drugs=(statin_monitoring_rules().add_on,)) for m in cur_meds):
            return "_maximal_on_add_on"
        return "_maximal" if acted else "_maximal_review"
    return "" if acted else "_review"


def _is_tachycardic(hr: float, patient: Any, vital: Any, ctx: NarrativeContext) -> bool:
    """Whether ``hr`` is above normal: above the pediatric heart-rate range
    for the age on the measurement day, else (adults, unknown age) the adult
    limit ``NARRATIVE_ADULT_TACHYCARDIA_HR`` (Issue #2986)."""
    when = _o(vital, "timestamp", None) if vital is not None else None
    if when is None:
        when = _o(ctx.encounter, "admission_datetime", None) if ctx.encounter is not None else None
    rng = pediatric_vital_range("heart_rate", age_in_completed_months(_o(patient, "date_of_birth", None), when))
    return is_tachycardic_hr(hr, rng.high if rng is not None else None)


def _doac_monitoring_values(
    lab_by_name: dict[str, tuple[Any, str | None]], measured_on: dict[str, str], lang: str
) -> list[str]:
    """The renal function and blood count of a DOAC patient, as cited in the
    AF assessment (Issue #2993): eGFR (else creatinine), then Hb; a result of
    an earlier visit carries its date (Issue #3273)."""

    def _when(*names: str) -> str:
        for n in names:
            if n in measured_on:
                return t("outpatient_results.measured_on", lang, date=measured_on[n])
        return ""

    out: list[str] = []
    egfr = lab_by_name.get("egfr")
    cr = lab_by_name.get("cr") or lab_by_name.get("creatinine")
    if egfr:
        v, u = egfr
        out.append(f"eGFR {v} {'mL/min/1.73m²' if not u or '1.73' in str(u) else u}{_when('egfr')}")
    elif cr:
        v, u = cr
        out.append(f"Cr {v} {u or 'mg/dL'}{_when('creatinine', 'cr')}")
    hb = lab_by_name.get("hb") or lab_by_name.get("hemoglobin")
    if hb:
        v, u = hb
        out.append(f"Hb {v} {u or 'g/dL'}{_when('hb', 'hemoglobin')}")
    return out


# ─────────────────────────────────────────────────────────────────────
# PLAN
# ─────────────────────────────────────────────────────────────────────


@section("plan")
def build_outpatient_plan(generator: TemplateNarrativeGenerator, ctx: NarrativeContext) -> tuple[str, list[str]]:
    """Build SOAP plan from outpatient_soap_template.plan_<lang>.

    v9 (2026-08-17) density fix — v8 emitted only continuation-med list
    (英字 + "他 N 剤"). This version composes a multi-line plan
    including continuation Rx (JA localized), today's discharge_prescription
    (if any), procedures ordered today, and a follow-up sentinel.
    """
    facts: list[str] = []
    lang = ctx.target_lang
    fallback = t("fallback.generic_plan", lang)

    kind = visit_kind(ctx)
    # Issue #3251: each vital-sign finding of the Assessment has its plan line.
    vital_plans = [plan for _finding, plan in _visit_vital_findings(ctx)]
    # Issues #3231 / #3250: the plan lines of the chronic-problem judgements
    # (BP above target, DOAC renal check) and of the abnormal results.
    vital_plans = [
        *dict.fromkeys(_chronic_assessment(ctx).plans),
        *(line for _finding, plan in _visit_result_findings(ctx) for line in plan.split("\n") if line),
        *vital_plans,
    ]
    # Issues #3249 / #3252: the next visit the visit reason calls for (None:
    # the chronic follow-up line; "": no scheduled return).
    reason_next = next_visit_line(ctx, kind)

    # Issues #3249 / #3252: the visit reason's plan (and the vaccines given).
    reason_plan = kind_lines(ctx, kind, "plan")
    if reason_plan:
        facts.append("composed:visit_reason.plan")

    soap = _get_soap_template(ctx)
    if soap is not None:
        text = _pick_localized(soap, "plan", lang, ctx)
        if text:
            text = "\n".join([text, *reason_plan])
            facts.append(f"encounter_protocol.narrative.outpatient_soap_template.plan_{lang}")
            # Issue #1180: the YAML `plan_<lang>` is a per-condition
            # constant, which made the Plan section byte-identical
            # across every visit in 92.1% of patients. Append a
            # per-encounter varying follow-up line so consecutive
            # visits show different cadence (band chosen per chronic
            # condition, index rotated deterministically off
            # (patient_id, encounter_id)). Preserves the YAML content
            # as the baseline; only adds a new tail line.
            titration = _compose_statin_titration_line(ctx)
            if titration:
                text = f"{text}\n{titration}"
                facts.append("ctx.discharge_medications.titration")
            if vital_plans:
                text = "\n".join([text, *vital_plans])
                facts.append("ctx.vitals.today")
            template_holds = _compose_safety_hold_lines(ctx)
            if template_holds:
                text = "\n".join([text, *template_holds])
                facts.append("ctx.prior_safety_holds")
            tail = _compose_follow_up_line(ctx)
            if tail:
                facts.append("encounter_protocol.next_visit_interval")
                return f"{text}\n{tail}", facts
            return text, facts

    # v9 multi-line composition (density fix)
    lines: list[str] = reason_plan
    titration = _compose_statin_titration_line(ctx)
    if titration:
        lines.append(titration)
        facts.append("ctx.discharge_medications.titration")
    # Issue #3250: one medication list. With a prescription issued at the
    # visit, that prescription and its difference from the medications at the
    # start of the visit; without one, the medications continued.
    today_rx = _compose_today_prescription_line(ctx)
    if today_rx:
        lines.append(today_rx)
        facts.append("ctx.discharge_medications")
        changes = _compose_medication_changes_line(ctx)
        if changes:
            lines.append(changes)
            facts.append(home_medications_at_admission(ctx)[1])
    else:
        continuation = _compose_current_medications_line(ctx)
        if continuation:
            lines.append(continuation)
            facts.append(home_medications_at_admission(ctx)[1])
    # Issue #3250: a drug held for a safety reason during an earlier admission.
    hold_lines = _compose_safety_hold_lines(ctx)
    if hold_lines:
        lines.extend(hold_lines)
        facts.append("ctx.prior_safety_holds")

    today_procs = _compose_today_procedures_line(ctx)
    if today_procs:
        lines.append(today_procs)
        facts.append("ctx.procedures.today")

    if vital_plans:
        lines.extend(vital_plans)
        facts.append("ctx.vitals.today")

    # Issue #3465: the actual next visit wins over the visit reason's cadence;
    # "" (no scheduled return) stays empty.
    actual_next = "" if reason_next == "" else _actual_next_visit_line(ctx)
    follow_up = actual_next or (_compose_follow_up_line(ctx) if reason_next is None else reason_next)
    if follow_up:
        lines.append(follow_up)
        facts.append("encounter_protocol.next_visit_interval")

    # Issue #1066: append drug_safety avoidance/substitution reasoning
    # so outpatient chronic follow-up notes carry the same visibility
    # as inpatient progress notes.
    skips_addendum = _render_safety_skips_line(getattr(ctx, "safety_skips", None) or [], lang)
    if skips_addendum:
        lines.append(skips_addendum)
        facts.append("ctx.safety_skips")

    if lines:
        return "\n".join(lines), facts

    return fallback, facts


def _compose_statin_titration_line(ctx: NarrativeContext) -> str:
    """The statin stepped up at this visit and the LDL that called for it
    (Issue #2877); empty when none was."""
    from clinosim.locale.free_text import localize_drug_name

    for m in getattr(ctx, "discharge_medications", None) or []:
        from_dose = _o(m, "titrated_from_dose", "")
        if not from_dose:
            continue
        ldl = _o(m, "titration_ldl", None)
        return t(
            "prescription.statin_titrated",
            ctx.target_lang,
            med=localize_drug_name(str(_o(m, "drug_name", "")), ctx.target_lang),
            from_dose=from_dose,
            to_dose=_o(m, "dose", ""),
            ldl=f"{float(ldl):g}" if ldl is not None else "",
            date=_o(m, "titration_panel_on", ""),
        )
    return ""


def _compose_today_prescription_line(ctx: NarrativeContext) -> str:
    """Today's outpatient Rx (from ctx.discharge_medications when the
    outpatient visit closes with a fresh prescription). v9 density fix."""
    rx = list(getattr(ctx, "discharge_medications", None) or [])
    if not rx:
        return ""
    lang = ctx.target_lang
    parts: list[str] = []
    for m in rx:
        drug = _o(m, "drug_name", "") or ""
        if not drug:
            continue
        drug, _cat = strip_protocol_prefix(drug)
        # Drug-name katakana lookup via lang-aware wrapper.
        from clinosim.locale.free_text import localize_drug_name

        drug = localize_drug_name(drug, lang)
        bits: list[str] = [str(drug), *prescription_bits(m, lang, drug_name=str(drug))]
        parts.append(" ".join(bits))
    if not parts:
        return ""
    head = t("outpatient.today_prescription_head", lang) + (t("list_sep.semicolon", lang).join(parts))
    return head


def _compose_today_procedures_line(ctx: NarrativeContext) -> str:
    """Procedures / labs ordered today for the outpatient visit.
    v9 density fix — v8 P section ignored today's activity entirely."""
    procs = list(ctx.procedures or [])
    if not procs:
        return ""
    lang = ctx.target_lang
    names: list[str] = []
    seen: set[str] = set()
    for pr in procs:
        nm = _o(pr, "procedure_name", None) or _o(pr, "name", None) or _o(pr, "display_name", None)
        if not nm or nm in seen:
            continue
        seen.add(nm)
        names.append(str(nm))
    if not names:
        return ""
    head = t("outpatient.today_workup_head", lang) + t("list_sep.semicolon", lang).join(names)
    return head


def _actual_next_visit_line(ctx: NarrativeContext) -> str:
    days = next_visit_days(ctx)
    return t("prescription.next_visit", ctx.target_lang, days=days) if days else ""


def _compose_follow_up_line(ctx: NarrativeContext) -> str:
    """The next-visit line of the plan ("" when the record gives none).

    Issue #3465: the visit the patient is actually scheduled for comes first —
    the next outpatient visit of the same series (:func:`next_visit_days`) —
    then the encounter protocol's interval, then the chronic follow-up
    schedule's interval (Issue #2287, ``chronic_followup.yaml``). A visit with
    none of them states no next visit: the former per-encounter rotation over
    28 / 60 / 90 days (Issue #1180) invented an interval the schedule did not
    hold.
    """
    lang = ctx.target_lang
    actual = next_visit_days(ctx)
    if actual:
        return t("prescription.next_visit", lang, days=actual)
    ep = ctx.encounter_protocol
    interval = _o(ep, "next_visit_interval_days", None) if ep is not None else None
    if interval:
        try:
            d = int(interval)
            return t("prescription.next_visit", lang, days=d)
        except (TypeError, ValueError):
            pass
    patient = getattr(ctx, "patient", None)
    conditions = _o(patient, "chronic_conditions", []) if patient else []
    months = chronic_followup_interval_months(iter_chronic_codes(conditions))
    if months:
        phrase = "prescription.next_visit_month" if months == 1 else "prescription.next_visit_months"
        return t(phrase, lang, months=months)
    return ""


def _med_key(med: Any) -> str:
    """Identity of a medication across the home list and the prescription: the
    catalog drug id (of the id, else of the name), else the folded name."""
    name, _cat = strip_protocol_prefix(str(_o(med, "drug_name", "") or ""))
    return drug_key(str(_o(med, "drug_id", "") or name))


def _compose_safety_hold_lines(ctx: NarrativeContext) -> list[str]:
    """The Plan lines of the drugs held for a safety reason during an earlier
    encounter, within ``hold_followup_days`` of it (Issue #3250): the drug
    resumed on today's prescription (with the reason it was held), or still on
    hold (it is not on the prescription and not among the medications at the
    start of the visit). The latest hold of a drug counts."""
    from datetime import date as _date

    from clinosim.locale.free_text import localize_drug_name
    from clinosim.modules.document.narrative._outpatient_results import note_time, outpatient_results

    holds = list(getattr(ctx, "prior_safety_holds", None) or [])
    if not holds:
        return []
    lang = ctx.target_lang
    when = note_time(ctx)
    window = outpatient_results().hold_followup_days
    prescribed = {_med_key(m) for m in (getattr(ctx, "discharge_medications", None) or [])}
    at_start = {_med_key(m) for m in home_medications_at_admission(ctx)[0]}
    latest: dict[str, dict[str, Any]] = {}
    for hold in holds:
        try:
            held_on = _date.fromisoformat(str(hold.get("held_on", "")))
        except ValueError:
            continue
        if when is not None and not 0 <= (when.date() - held_on).days <= window:
            continue
        key = drug_key(str(hold.get("drug", "")))
        if key and (key not in latest or hold["held_on"] >= latest[key]["held_on"]):
            latest[key] = hold
    lines: list[str] = []
    for key, hold in latest.items():
        reason = str(hold.get(f"reason_{lang}") or hold.get("reason", ""))
        drug = str(localize_drug_name(str(hold.get("drug", "")), lang))
        if key in prescribed and key not in at_start:
            phrase = "outpatient_results.hold_resumed"
        elif key not in prescribed and key not in at_start:
            phrase = "outpatient_results.hold_continued"
        else:
            continue
        lines.append(t(phrase, lang, drug=drug, date=hold["held_on"], reason=reason))
    return lines


def _compose_medication_changes_line(ctx: NarrativeContext) -> str:
    """How today's prescription differs from the medications at the start of
    the visit (Issue #3250): drugs started, drugs whose dose changed, and home
    drugs not on the prescription ("not renewed", the prescription does not
    say they were stopped). An identical list says so."""
    from clinosim.locale.free_text import localize_drug_name

    lang = ctx.target_lang
    rx = [m for m in (getattr(ctx, "discharge_medications", None) or []) if _o(m, "drug_name", "")]
    if not rx:
        return ""
    home = {_med_key(m): m for m in home_medications_at_admission(ctx)[0] if _med_key(m)}
    today = {_med_key(m): m for m in rx}

    def _name(m: Any) -> str:
        return str(localize_drug_name(strip_protocol_prefix(str(_o(m, "drug_name", "")))[0], lang))

    def _dose(m: Any) -> str:
        return str(_o(m, "dose", "") or "").replace(" ", "").lower()

    started = [_name(m) for k, m in today.items() if k not in home]
    changed = [
        f"{_name(m)} ({_o(home[k], 'dose', '')} → {_o(m, 'dose', '')})"
        for k, m in today.items()
        if k in home and _dose(m) and _dose(home[k]) and _dose(m) != _dose(home[k])
    ]
    not_renewed = [str(_render_home_med_name(m, lang=lang)) for k, m in home.items() if k not in today]
    parts = [
        t(f"outpatient_results.med_{key}", lang, list=t("list_sep.semicolon", lang).join(names))
        for key, names in (("started", started), ("changed", changed), ("not_renewed", not_renewed))
        if names
    ]
    if not parts:
        return t("outpatient_results.med_unchanged", lang) if home else ""
    return t("outpatient_results.med_changes", lang, parts=t("list_sep.semicolon", lang).join(parts))


def _compose_current_medications_line(ctx: NarrativeContext) -> str:
    """List the patient's medications at the start of the visit for the Plan
    section (``home_medications_at_admission``: the record's snapshot, else the
    patient's ``current_medications``). Returns "" when the list is empty.

    v9 (2026-08-17): drug names JA localization enabled + truncate
    widened to 10 (v8 = 5, which frequently produced "他 N 剤"
    information loss for polypharmacy patients).
    """
    # Issue #3262: the medications at the start of the visit.
    meds = home_medications_at_admission(ctx)[0]
    if not meds:
        return ""
    lang = ctx.target_lang
    names: list[str] = []
    for m in meds:
        n = _render_home_med_name(m, lang=lang) if not isinstance(m, str) else m
        if isinstance(m, str):
            # Drug-name katakana lookup for str-only entries via
            # lang-aware wrapper (dict entries already routed through
            # `_render_home_med_name`).
            from clinosim.locale.free_text import localize_drug_name

            n = localize_drug_name(m, lang)
        if n:
            names.append(str(n))
    if not names:
        return ""
    # v9: widen truncate 5 → 10 to reduce "他 N 剤" information loss.
    # Polypharmacy patients (5+ chronic Rx) are the norm in geriatric
    # outpatient encounters — 10 covers the 90%ile.
    limit = 10
    shown = names[:limit]
    joiner = t("list_sep.serial", lang)
    head = joiner.join(shown)
    if len(names) > limit:
        head += t("current_medications.truncate_suffix", lang, n=len(names) - limit)
    return t("current_medications.line", lang, list=head)
