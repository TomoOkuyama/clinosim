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

import hashlib
from functools import cache
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

from clinosim.codes import display as registry_display
from clinosim.codes.valuesets import concept_group, iter_chronic_codes
from clinosim.locale.i18n import t
from clinosim.locale.loader import chronic_followup_interval_months
from clinosim.modules._shared import get_attr_or_key as _o
from clinosim.modules._shared import strip_protocol_prefix
from clinosim.modules.document.narrative._localization import _localize_complication
from clinosim.modules.document.narrative._narrative_interpretation_thresholds import (
    NARRATIVE_BP_HIGH_NORMAL_DBP_THRESHOLD,
    NARRATIVE_BP_HIGH_NORMAL_SBP_THRESHOLD,
    NARRATIVE_BP_HYPERTENSION_DBP_THRESHOLD,
    NARRATIVE_BP_HYPERTENSION_SBP_THRESHOLD,
    NARRATIVE_HBA1C_DIABETES_THRESHOLD,
    NARRATIVE_LDL_BORDERLINE_THRESHOLD,
    NARRATIVE_LDL_ELEVATED_THRESHOLD,
    NARRATIVE_LDL_HIGH_THRESHOLD,
)
from clinosim.modules.document.narrative._narrative_utils import _age_at
from clinosim.modules.document.narrative._template_helpers import (
    _label,
    _pick_localized,
    _render_home_med_name,
    _render_safety_skips_line,
)
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
    """Load `clinosim/codes/data/chronic-med-class-hints.yaml`.

    Returns a `{class_key: {prefix, en: [...], ja: [...]}}` dict.
    """
    path = Path(__file__).resolve().parents[5] / "codes" / "data" / "chronic-med-class-hints.yaml"
    with path.open(encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    classes = raw.get("classes") or {}
    out: dict[str, dict[str, Any]] = {}
    for class_key, row in classes.items():
        if isinstance(row, dict):
            out[str(class_key)] = row
    return out


def _chronic_med_class_hints(class_key: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Return `(en_hints, ja_hints)` tuple for a chronic-condition class.

    Looked up in `chronic-med-class-hints.yaml` by `class_key`
    (`hypertension`, `diabetes`, `dyslipidemia`, `afib_anticoagulation`,
    `copd`, `asthma`). Missing locale lists return `()` — the caller's
    `_pick_med_containing` treats that as "no med cited".
    """
    row = _chronic_med_class_hints_raw().get(class_key) or {}
    en = tuple(str(h) for h in (row.get("en") or []) if isinstance(h, str))
    ja = tuple(str(h) for h in (row.get("ja") or []) if isinstance(h, str))
    return (en, ja)


# ─────────────────────────────────────────────────────────────────────
# SOAP template resolver (3-layer fallback chain).
# ─────────────────────────────────────────────────────────────────────


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
    """
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
    if ctx.target_lang == "ja":
        from clinosim.modules.document.narrative._chronic_soap import resolve_chronic_soap

        patient = ctx.patient
        if patient is not None:
            conds = _o(patient, "chronic_conditions", []) or []
            chronic_tmpl = resolve_chronic_soap(conds)
            if chronic_tmpl is not None:
                return chronic_tmpl
    return None


# ─────────────────────────────────────────────────────────────────────
# SUBJECTIVE
# ─────────────────────────────────────────────────────────────────────


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
    soap = _get_soap_template(ctx)
    template_prose = ""
    if soap is not None:
        template_prose = _pick_localized(soap, "subjective", lang, ctx)
        if template_prose == fallback:
            template_prose = ""
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
    cc = ""
    if enc is not None:
        cc = _o(enc, f"chief_complaint_{lang}", None) or _o(enc, "chief_complaint", None) or ""
    cc = str(cc)
    # Chronic condition follow-up context (short list, code-lookup localized).
    # Issue #1333: route CIF base code through map_diagnosis_code so the
    # narrative display matches the FHIR emit-target (US F00 → F03.90
    # renders as "Unspecified dementia", not the WHO parent-code
    # "Dementia in Alzheimer disease").
    from clinosim.codes import lookup as _code_lookup
    from clinosim.modules.output.fhir_r4.lib.common import (
        map_diagnosis_code as _map_diagnosis_code,
    )

    country = "JP" if ctx.locale.lower() == "jp" else "US"
    conditions = _o(patient, "chronic_conditions", []) or []
    chronic_labels: list[str] = []
    for c in conditions[:3]:
        code = _o(c, "code", "") or (c if isinstance(c, str) else "")
        if not code:
            continue
        emit_code = _map_diagnosis_code(code, country) or code
        key = _label("code_system_icd_display", "primary", lang)
        disp = _code_lookup(key, emit_code, lang)
        # Issue #1777: when the display lookup misses, SKIP the entry
        # rather than leak the raw ICD code into narrative free text.
        # The prose sentence "Follow-up of chronic conditions: G47.30"
        # reads as a coding sheet, not a clinical note; a shorter list
        # with only resolvable items reads correctly.
        if not disp or disp == emit_code:
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
    if chronic_labels:
        sep = t("list_sep.serial", lang)
        parts.append(t("outpatient.chronic_followup", lang, list=sep.join(chronic_labels)))
    text = "".join(parts).strip()
    return text


# ─────────────────────────────────────────────────────────────────────
# OBJECTIVE
# ─────────────────────────────────────────────────────────────────────


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
    template_prose = ""
    soap = _get_soap_template(ctx)
    if soap is not None:
        template_prose = _pick_localized(soap, "objective", lang, ctx)
        if template_prose == fallback:
            # _fill_template_placeholders returned the fallback marker
            # (unresolvable placeholder); treat as empty so vitals alone
            # supply the section.
            template_prose = ""

    if vital_line and template_prose:
        facts.extend(["ctx.vitals", "outpatient_soap_template.objective"])
        return f"{vital_line}。{template_prose.strip()}", facts
    if vital_line:
        facts.append("ctx.vitals")
        return vital_line, facts
    if template_prose:
        facts.append("outpatient_soap_template.objective")
        return template_prose.strip(), facts
    return fallback, facts


# ─────────────────────────────────────────────────────────────────────
# ASSESSMENT
# ─────────────────────────────────────────────────────────────────────


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
        labels = []
        for code in primary_dx_codes:
            # Strip pediatric/other prefixes — try registry lookup first
            disp = registry_display(disp_key, code, lang) or code
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
    lang = ctx.target_lang
    # Phase 1c-6 (2026-09-23): prefer the locale-specific
    # ``chief_complaint_{ja,en}`` over the raw ``chief_complaint``
    # so JA output emits 「来院理由: 予防接種」 rather than the
    # underlying-EN 「来院理由: Vaccination visit」 for encounters
    # (immunization / vaccination visits, ED follow-ups) whose
    # emitters populate both language slots. Mirrors the pattern in
    # `_render_outpatient_chronic_soap` (line 5258).
    cc = _o(enc, f"chief_complaint_{lang}", None) or _o(enc, "chief_complaint", "") or ""
    cc = str(cc).strip()
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
    labels: list[str] = []
    for c in conditions:
        code = _o(c, "code", "") or (c if isinstance(c, str) else "")
        if not code:
            continue
        disp_key = _label("code_system_icd_display", "primary", lang)
        disp = registry_display(disp_key, code, lang) or code
        labels.append(disp)
    if not labels:
        return ""
    sep = t("list_sep.serial", lang)
    return t("chronic.followup_head", lang, list=sep.join(labels))


def _compose_chronic_assessment_integrated(ctx: NarrativeContext) -> str:
    """SOAP Assessment enriched with today's vitals + labs + target
    comparison prose (Issue #985 personalization).

    v9 emitted a chronic-condition list; v9-density integrated abnormal
    labs but only fired on ``flag`` presence and lacked target-reference
    prose. #985 lifts:

      - Cites the patient's actual value regardless of flag (a
        controlled HbA1c 6.8% is still worth citing against target
        7.0% — that's the point of the follow-up assessment).
      - Adds explicit target reference (JDS DM HbA1c < 7.0%, JAS
        LDL < 120 mg/dL primary prevention, JSH BP < 140/90 mmHg,
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
    if patient is None:
        return ""
    conditions = _o(patient, "chronic_conditions", []) or []
    # Issue #1183: the empty-conditions early return silently dropped
    # abnormal-vital lines for patients with no chronic conditions.
    # Continue into the loop with an empty condition list; the
    # vital-abnormal pass at the end still fires.
    vitals = list(ctx.vitals or [])
    labs = list(ctx.lab_results or [])
    v0 = vitals[0] if vitals else None
    sbp = _o(v0, "systolic_bp", None) if v0 else None
    dbp = _o(v0, "diastolic_bp", None) if v0 else None
    # Issue #1181: cast remaining vitals to floats up-front so the
    # observation-aware fallback below can quote them without a
    # try/except per branch (also consumed by the #1183 vital-abnormal
    # handler after the condition-dispatch loop).
    _hr_raw = _o(v0, "heart_rate", None) if v0 else None
    _t_raw = _o(v0, "temperature_celsius", None) if v0 else None
    _spo2_raw = _o(v0, "spo2", None) if v0 else None
    try:
        hr_f = float(_hr_raw) if _hr_raw is not None else None
    except (TypeError, ValueError):
        hr_f = None
    try:
        temp_f = float(_t_raw) if _t_raw is not None else None
    except (TypeError, ValueError):
        temp_f = None
    try:
        spo2_f = float(_spo2_raw) if _spo2_raw is not None else None
    except (TypeError, ValueError):
        spo2_f = None

    # Issue #985: cite value regardless of flag — a target-comparison
    # assessment needs the actual number even when in-range.
    lab_by_name: dict[str, tuple[Any, str | None]] = {}
    for lab in labs:
        name = str(_o(lab, "lab_name", "") or "").lower()
        val = _o(lab, "value", None)
        if not name or val is None:
            continue
        lab_by_name[name] = (val, _o(lab, "unit", None))

    lang = ctx.target_lang
    disp_key = "icd-10" if ctx.locale == "jp" else "icd-10-cm"

    # Pre-resolve current-medications for continuation-tail. Issue #1033:
    # rendering always as ``lang="ja"`` leaks katakana drug names into US
    # assessment prose (`Metformin continue` → `メトホルミン continue`).
    # Render in the target locale and match hints in the target locale so
    # a US assessment cites the English drug name and a JP assessment
    # cites the katakana name.
    cur_meds = _o(patient, "current_medications", []) or []
    med_names_display = [_render_home_med_name(m, lang=ctx.target_lang) for m in cur_meds]
    med_names_display = [n for n in med_names_display if n]

    def _pick_med_containing(en_hints: tuple[str, ...], ja_hints: tuple[str, ...]) -> str | None:
        """Return the first current-med whose (locale-rendered) name
        contains any hint. Hints must be provided for both locales — the
        match set is chosen by ``ctx.target_lang`` so a US assessment
        searches on English tokens and a JP assessment on katakana.
        """
        hints = ja_hints if lang == "ja" else en_hints
        for n in med_names_display:
            for h in hints:
                if h in n:
                    return n
        return None

    def _pick_med_by_class(class_key: str) -> str | None:
        """Shorthand for `_pick_med_containing(*_chronic_med_class_hints(key))`."""
        en, ja = _chronic_med_class_hints(class_key)
        return _pick_med_containing(en_hints=en, ja_hints=ja)

    lines: list[str] = []
    for i, c in enumerate(conditions, 1):
        code = _o(c, "code", "") or (c if isinstance(c, str) else "")
        if not code:
            continue
        label = registry_display(disp_key, code, ctx.target_lang) or code
        code_prefix = code.split(".")[0].upper()
        interp = ""

        # ── I10: Essential hypertension ────────────────────────────
        if code_prefix.startswith("I10") and sbp and dbp:
            if sbp >= NARRATIVE_BP_HYPERTENSION_SBP_THRESHOLD or dbp >= NARRATIVE_BP_HYPERTENSION_DBP_THRESHOLD:
                ctrl = t("control_status.poorly_controlled", lang)
            elif sbp >= NARRATIVE_BP_HIGH_NORMAL_SBP_THRESHOLD or dbp >= NARRATIVE_BP_HIGH_NORMAL_DBP_THRESHOLD:
                ctrl = t("control_status.high_normal", lang)
            else:
                ctrl = t("control_status.at_goal", lang)
            target = t(
                "chronic_assessment.bp_target",
                lang,
                sbp=NARRATIVE_BP_HYPERTENSION_SBP_THRESHOLD,
                dbp=NARRATIVE_BP_HYPERTENSION_DBP_THRESHOLD,
            )
            med = _pick_med_by_class("hypertension")
            med_tail = t("chronic_assessment.med_continue_tail", lang, med=med) if med else ""
            interp = f"BP {int(sbp)}/{int(dbp)} mmHg — {target} — {ctrl}{med_tail}" + t("list_sep.period", lang)

        # ── E11 / E10: Diabetes mellitus ───────────────────────────
        elif concept_group("diabetes").contains(code_prefix):
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
                parts_dm.append(
                    f"HbA1c {v}{u or '%'} — {target} — {ctrl}" if ctrl else f"HbA1c {v}{u or '%'} — {target}"
                )
            # 尿アルブミン (pertinent info when measured)
            ualb = lab_by_name.get("urine_albumin") or lab_by_name.get("albuminuria")
            if ualb:
                v, u = ualb
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
                    parts_dm.append(t("chronic_labs.glucose_line", lang, value=v_g, unit=u_g or "mg/dL"))
            med = _pick_med_by_class("diabetes")
            if med:
                parts_dm.append(t("prescription.medication_continue", lang, med=med))
            if parts_dm:
                interp = t("list_sep.serial", lang).join(parts_dm) + t("list_sep.period", lang)

        # ── E78: Dyslipidemia ──────────────────────────────────────
        elif code_prefix.startswith("E78"):
            ldl = lab_by_name.get("ldl")
            if ldl:
                v, u = ldl
                try:
                    vf = float(v)
                    if vf >= NARRATIVE_LDL_HIGH_THRESHOLD:
                        ctrl = t("control_status.high_ldl_statin_underresponse", lang)
                    elif vf >= NARRATIVE_LDL_BORDERLINE_THRESHOLD:
                        ctrl = t("control_status.borderline_intensification", lang)
                    elif vf >= NARRATIVE_LDL_ELEVATED_THRESHOLD:
                        ctrl = t("control_status.elevated", lang)
                    else:
                        ctrl = t("control_status.at_goal", lang)
                except (TypeError, ValueError):
                    ctrl = ""
                target = t(
                    "chronic_assessment.ldl_target_primary_prevention",
                    lang,
                    ldl=NARRATIVE_LDL_ELEVATED_THRESHOLD,
                )
                med = _pick_med_by_class("dyslipidemia")
                med_tail = t("chronic_assessment.med_continue_tail", lang, med=med) if med else ""
                interp = f"LDL {v} {u or 'mg/dL'} — {target} — {ctrl}{med_tail}" + t("list_sep.period", lang)

        # ── N18: Chronic kidney disease ────────────────────────────
        elif code_prefix.startswith("N18"):
            parts_ckd: list[str] = []
            cr = lab_by_name.get("cr") or lab_by_name.get("creatinine")
            egfr = lab_by_name.get("egfr")
            if egfr:
                v, u = egfr
                try:
                    vf = float(v)
                    if vf >= 90:
                        stage = "G1"
                    elif vf >= 60:
                        stage = "G2"
                    elif vf >= 45:
                        stage = "G3a"
                    elif vf >= 30:
                        stage = "G3b"
                    elif vf >= 15:
                        stage = "G4"
                    else:
                        stage = "G5"
                except (TypeError, ValueError):
                    stage = ""
                stage_ja = t("chronic_labs.ckd_stage", lang, stage=stage)
                # UCUM eGFR unit "mL/min/{1.73_m2}" carries a `{}`
                # annotation that reads as a placeholder in narrative.
                # Prefer the plain human display for prose emit.
                display_u = "mL/min/1.73m²" if u and "1.73" in str(u) else (u or "mL/min/1.73m²")
                parts_ckd.append(f"eGFR {v} {display_u} ({stage_ja})")
            if cr and not egfr:
                v, u = cr
                parts_ckd.append(f"Cr {v} {u or 'mg/dL'}")
            if parts_ckd:
                interp = t("list_sep.serial", lang).join(parts_ckd) + (t("chronic_monitoring.renal_function", lang))

        # ── I48: Atrial fibrillation / flutter ─────────────────────
        # Anticoagulation is the primary monitoring axis. INR is the
        # therapeutic marker for warfarin (2.0-3.0 for non-valvular
        # AFib per ACC/AHA + JCS guidelines); DOACs skip INR but the
        # med-continuation tail still records the drug.
        elif code_prefix.startswith("I48"):
            parts_afib: list[str] = []
            inr = lab_by_name.get("pt-inr") or lab_by_name.get("pt_inr") or lab_by_name.get("inr")
            if inr:
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
                interp = t("list_sep.serial", lang).join(bits2) + (t("chronic_monitoring.act_control_review", lang))

        if interp:
            lines.append(f"{i}. {label}: {interp}")
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
            if condition_stage:
                follow = t(
                    "chronic_assessment.chronic_stage_stable",
                    lang,
                    label=label,
                    stage=condition_stage,
                )
                lines.append(follow)
            else:
                follow = t("chronic_assessment.chronic_noted", lang, label=label)
                lines.append(f"{i}. {follow}")

    # Issue #1183: Assessment previously ignored abnormal vitals that
    # were not paired with a matching chronic condition. Tachycardia
    # was acknowledged in 2.5% of notes (20/790), hypoxemia in 0%
    # (0/1,890), and fever in only 6.7% (2/30). Add a per-vital pass
    # after the condition-dispatch loop so a HR ≥100 / SpO2 <95 /
    # T ≥38 always surfaces in the Assessment prose regardless of
    # the chronic-condition list. hr_f / temp_f / spo2_f are already
    # parsed once at the top of this method (shared with PR B3's
    # observation-aware fallback).
    vital_lines: list[str] = []
    if hr_f is not None and hr_f >= 100:
        vital_lines.append(t("chronic_assessment.tachycardia", lang, hr=int(round(hr_f))))
    if spo2_f is not None and spo2_f < 95:
        key = "chronic_assessment.hypoxemia_severe" if spo2_f < 90 else "chronic_assessment.hypoxemia"
        vital_lines.append(t(key, lang, spo2=spo2_f))
    if temp_f is not None and temp_f >= 38.0:
        vital_lines.append(t("chronic_assessment.fever", lang, temp=temp_f))
    # Append with continued numbering so the Assessment reads as one list.
    start = len(lines) + 1
    for j, extra in enumerate(vital_lines):
        lines.append(f"{start + j}. {extra}")

    if not lines:
        return ""
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────
# PLAN
# ─────────────────────────────────────────────────────────────────────


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

    soap = _get_soap_template(ctx)
    if soap is not None:
        text = _pick_localized(soap, "plan", lang, ctx)
        if text:
            facts.append(f"encounter_protocol.narrative.outpatient_soap_template.plan_{lang}")
            # Issue #1180: the YAML `plan_<lang>` is a per-condition
            # constant, which made the Plan section byte-identical
            # across every visit in 92.1% of patients. Append a
            # per-encounter varying follow-up line so consecutive
            # visits show different cadence (band chosen per chronic
            # condition, index rotated deterministically off
            # (patient_id, encounter_id)). Preserves the YAML content
            # as the baseline; only adds a new tail line.
            tail = _compose_follow_up_line(ctx)
            if tail:
                facts.append("encounter_protocol.next_visit_interval")
                return f"{text}\n{tail}", facts
            return text, facts

    # v9 multi-line composition (density fix)
    lines: list[str] = []
    continuation = _compose_current_medications_line(ctx)
    if continuation:
        lines.append(continuation)
        facts.append("ctx.patient.current_medications")

    today_rx = _compose_today_prescription_line(ctx)
    if today_rx:
        lines.append(today_rx)
        facts.append("ctx.discharge_medications")

    today_procs = _compose_today_procedures_line(ctx)
    if today_procs:
        lines.append(today_procs)
        facts.append("ctx.procedures.today")

    follow_up = _compose_follow_up_line(ctx)
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


def _compose_today_prescription_line(ctx: NarrativeContext) -> str:
    """Today's outpatient Rx (from ctx.discharge_medications when the
    outpatient visit closes with a fresh prescription). v9 density fix."""
    rx = list(getattr(ctx, "discharge_medications", None) or [])
    if not rx:
        return ""
    lang = ctx.target_lang
    parts: list[str] = []
    for m in rx[:8]:
        drug = _o(m, "drug_name", "") or ""
        if not drug:
            continue
        drug, _cat = strip_protocol_prefix(drug)
        # Drug-name katakana lookup via lang-aware wrapper.
        from clinosim.modules.output.fhir_r4.lib.localization import localize_drug_name

        drug = localize_drug_name(drug, lang)
        dose = _o(m, "dose", "") or ""
        route = _o(m, "route", "") or ""
        freq = _o(m, "frequency", "") or ""
        days = _o(m, "days_supply", None)
        bits: list[str] = [str(drug)]
        if dose:
            bits.append(str(dose))
        if route:
            bits.append(str(route))
        if freq:
            bits.append(str(freq))
        if days:
            bits.append(t("prescription.days_supply_suffix", lang, days=days))
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
    for pr in procs[:6]:
        nm = _o(pr, "procedure_name", None) or _o(pr, "name", None) or _o(pr, "display_name", None)
        if not nm or nm in seen:
            continue
        seen.add(nm)
        names.append(str(nm))
    if not names:
        return ""
    head = t("outpatient.today_workup_head", lang) + t("list_sep.semicolon", lang).join(names)
    return head


def _compose_follow_up_line(ctx: NarrativeContext) -> str:
    """Follow-up guidance from encounter_protocol (未確定 — treat as
    planning, not fact). v9 density fix.

    Issue #1180: in 92.1% of patients the Plan section was byte-identical
    across every outpatient visit because the sentinel `1 か月後` and
    the per-condition YAML `plan_ja` never varied by visit. Add a
    per-encounter deterministic rotation over a small band of
    clinically-plausible intervals so consecutive visits show
    different follow-up cadence.

    Issue #2287: a patient with followed-up chronic conditions gets the
    interval their visits are scheduled at instead.
    """
    ep = ctx.encounter_protocol
    interval = _o(ep, "next_visit_interval_days", None) if ep is not None else None
    lang = ctx.target_lang
    if interval:
        try:
            d = int(interval)
            return t("prescription.next_visit", lang, days=d)
        except (TypeError, ValueError):
            pass
    # Issue #2287: a patient with followed-up chronic conditions is seen at the
    # interval the population calendar schedules (chronic_followup.yaml), so
    # the note states that interval.
    patient = getattr(ctx, "patient", None)
    conditions = _o(patient, "chronic_conditions", []) if patient else []
    months = chronic_followup_interval_months(iter_chronic_codes(conditions))
    if months:
        phrase = "prescription.next_visit_month" if months == 1 else "prescription.next_visit_months"
        return t(phrase, lang, months=months)
    # #1180: no chronic schedule — a per-encounter deterministic rotation over
    # a small band of plausible intervals (days) so consecutive visits read
    # with clinical variation rather than as identical template text.
    band = (28, 60, 90)
    # Deterministic per-encounter rotation — same encounter always emits
    # the same interval, but consecutive encounters of the same patient
    # cycle through the band.
    enc = getattr(ctx, "encounter", None)
    enc_id = _o(enc, "encounter_id", "") or ""
    pat_id = getattr(patient, "patient_id", "") if patient else ""
    key = f"{pat_id}|{enc_id}|follow_up_interval".encode()
    idx = int.from_bytes(hashlib.sha256(key).digest()[:4], "big") % len(band)
    d = band[idx]
    return t("prescription.next_visit", lang, days=d)


def _compose_current_medications_line(ctx: NarrativeContext) -> str:
    """List the patient's current medications for the Plan section.

    Reads from `ctx.patient.current_medications` (chronic Rx list, populated
    by the population enricher). Returns "" when the list is empty.

    v9 (2026-08-17): drug names JA localization enabled + truncate
    widened to 10 (v8 = 5, which frequently produced "他 N 剤"
    information loss for polypharmacy patients).
    """
    patient = ctx.patient
    meds = _o(patient, "current_medications", []) or []
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
            from clinosim.modules.output.fhir_r4.lib.localization import localize_drug_name

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
