"""assessment_and_plan section builder for ADMISSION_HP / DISCHARGE_SUMMARY.

Extracted verbatim from ``template_generator.TemplateNarrativeGenerator``
as step C1m of the full-review Phase C renderer split (CRITICAL C1).
Behavior is byte-identical.

The builder is a free-standing ``(generator, ctx) -> (text, facts)``
function; the method on the class is a thin delegator so
``renderers/composition_sections.py`` (which looks up
``generator._build_<section>`` by name) stays unchanged.

Two outpatient/admission-only composer helpers moved alongside:
  - ``_compose_ap_assessment_from_state`` — EN+JA CIF-composed A line
    (Issue #1156 EN parity + session-88j P1-12/Bug-3 severity leak fix)
  - ``_compose_ap_plan_from_state`` — LOS estimate + day-0 meds +
    workup procedures (Issue #1156 EN parity + Issue #1185 F4 LOS
    agreement)

Generator-threaded helpers:
  - ``generator._resolve_daily_trajectory_with_source`` (JA day_0
    trajectory source)
  - ``generator._estimated_los_days`` (shared with care_plans — the
    AT-ADMISSION canonical LOS resolver, see Issue #1185 F4)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from clinosim.countries import country_code, has_authored_narrative
from clinosim.locale.i18n import t
from clinosim.modules._shared import get_attr_or_key as _o
from clinosim.modules.document.narrative._localization import _localize_complication
from clinosim.modules.document.narrative.renderers._shared_helpers import (
    chronic_condition_label,
    ordered_chronic_conditions,
    procedure_names,
)
from clinosim.modules.document.narrative.renderers.section_builders._registry import section
from clinosim.types.document import NarrativeContext

if TYPE_CHECKING:
    from clinosim.modules.document.narrative.template_generator import (
        TemplateNarrativeGenerator,
    )


@section("assessment_and_plan")
def build_assessment_and_plan(generator: TemplateNarrativeGenerator, ctx: NarrativeContext) -> tuple[str, list[str]]:
    """Build assessment_and_plan from daily_trajectory day_0 assessment + plan."""
    facts: list[str] = []
    lang = ctx.target_lang

    # Issue #1156: EN branch previously short-circuited to the
    # generic "Clinical assessment ongoing. Plan: Continue current
    # management." string for every admission, disconnecting the
    # H&P A&P section from the chief complaint. The EN branch now
    # calls the same CIF-derived composers as JA (which were made
    # language-aware in the same fix), so an asthma-exacerbation
    # admission reads "Admitted for evaluation and management of:
    # Severe wheezing... Initial medications: Prednisone, Albuterol..."
    # instead of the disconnected generic fallback. daily_trajectory
    # YAML content is still JA-only so EN skips that source.
    if not has_authored_narrative(lang):
        facts.append("composed:cif_state_en")
        _en_assessment = _compose_ap_assessment_from_state(ctx) or t("fallback.generic_assessment", lang)
        _en_plan = _compose_ap_plan_from_state(generator, ctx) or t("fallback.generic_plan", lang)
        return (
            t("ap_combined.assessment_plan_inline", lang, assessment=_en_assessment, plan=_en_plan),
            facts,
        )

    traj, traj_src = generator._resolve_daily_trajectory_with_source(ctx, ctx.clinical_course_archetype, 0)
    if traj_src:
        facts.append(traj_src)

    _generic_a = t("fallback.generic_assessment", lang)
    _generic_p = t("fallback.generic_plan", lang)
    # v9 (2026-08-17) density fix — v8 emitted only 19-char
    # "評価: 経過観察中。方針: 治療継続。". Compose an A&P from CIF
    # facts (diagnosis + severity + orders/procedures/meds today +
    # LOS estimate) so the section is clinically informative even
    # when disease YAML has no day_0 trajectory content. The
    # placeholder-aware _prefer helper matches the pattern used in
    # _render_progress_note_text.
    _placeholders = {_generic_a, _generic_p, ""}
    traj_a = traj.get("assessment")
    traj_p = traj.get("plan")
    assessment = (
        traj_a if (traj_a and traj_a not in _placeholders) else (_compose_ap_assessment_from_state(ctx) or _generic_a)
    )
    if traj_p and traj_p not in _placeholders:
        plan = t("list_sep.chunk", lang).join([traj_p, *admission_order_items(ctx), *admission_plan_items(ctx)])
    else:
        plan = _compose_ap_plan_from_state(generator, ctx) or _generic_p
    text = t("ap_combined.assessment_plan_block", lang, assessment=assessment, plan=plan)
    return text, facts


def _compose_ap_assessment_from_state(ctx: NarrativeContext) -> str:
    """admission_hp Assessment composed from CIF (v9 density fix).

    Issue #1156: prior to session-103 this composer returned ""
    for non-JA locales, forcing EN admission H&P sections into the
    ``Clinical assessment ongoing`` fallback regardless of the
    actual chief complaint / disease / severity. EN branch now
    parallels the JA structure (same CIF sources, English wording).
    """
    lang = ctx.target_lang
    parts: list[str] = []
    enc = ctx.encounter
    # Primary reason — try the localized ``chief_complaint_<lang>``
    # slot first, then fall back to the language-agnostic base
    # ``chief_complaint`` field. Preserves the pre-Phase-1d-18
    # behaviour: JA reads chief_complaint_ja first, EN reads
    # chief_complaint first (there is no chief_complaint_en slot on
    # PatientProfile) — but the branch is now data-driven.
    if enc is None:
        cc = None
    else:
        cc = _o(enc, f"chief_complaint_{lang}", None) or _o(enc, "chief_complaint", None)
    if cc:
        parts.append(t("ap_assessment.chief_complaint_line", lang, cc=cc))
    # Severity + disease
    # session-88j P1-12/Bug-3: JA output must not leak raw EN severity
    # (mild / moderate / severe / critical) into 「病態: X (Y)」. v14
    # review found 8/1084 admission_hp narratives with EN severity.
    # Localize severity for JA locale via the shared JA severity map.
    if ctx.disease_protocol is not None:
        disease = _o(ctx.disease_protocol, "disease_id", None)
        if disease:
            _sev = str(ctx.severity or "")
            from clinosim.modules.document.narrative._replacement_localization import localize_token

            _sev = localize_token(_sev, "severity", lang)
            # Phase 1c-2 (2026-09-22): the raw disease_id snake_case
            # token ("bacterial_pneumonia", "acute_myocardial_infarction")
            # leaked into JA narratives.
            # ``_localize_complication`` covers the disease-id vocabulary
            # too because ``disease_id`` and complication tokens draw
            # from the same disease-YAML namespace.
            disease_label = _localize_complication(str(disease), lang)
            parts.append(t("ap_assessment.disease_severity_line", lang, disease=disease_label, severity=_sev))
    # Chronic backdrop — Issue #1333: route CIF base code through
    # map_diagnosis_code so display matches the FHIR emit-target.
    # Issue #3248: every condition, the admission's own problem first.
    conds = ordered_chronic_conditions(ctx)
    if conds:
        country = country_code(ctx.locale)
        sex = str(_o(ctx.patient, "sex", "") or "")

        def _resolve_chronic_label(c: object) -> str:
            # Issue #2994: the label of the condition the output codes.
            base = _o(c, "code", "") or ""
            return (chronic_condition_label(base, country, lang, sex) or base) if base else ""

        labels = [_resolve_chronic_label(c) for c in conds]
        labels = [lbl for lbl in labels if lbl]
        if labels:
            sep = t("list_sep.serial", lang)
            parts.append(t("ap_assessment.comorbidities_line", lang, list=sep.join(labels)))
    if not parts:
        parts.append(t("ap_assessment.acute_fallback", lang))
    return t("list_sep.chunk", lang).join(parts)


def _compose_ap_plan_from_state(generator: TemplateNarrativeGenerator, ctx: NarrativeContext) -> str:
    """admission_hp Plan composed from CIF (v9 density fix).

    Issue #1156: EN branch added — parallels the JA structure so
    the EN admission H&P plan section carries LOS estimate, day-0
    medication orders, and workup procedures instead of the
    ``Continue current management`` fallback.
    """
    lang = ctx.target_lang
    parts: list[str] = []
    # LOS estimate — Issue #1185 F4: two sections of the same admission_hp
    # document reported different planned LOS numbers (25日 vs 17日)
    # because `_compose_ap_plan_from_state` used `ctx.los_days` (the
    # actual observed LOS) while `build_acp_estimated_los` used the
    # canonical `_estimated_los_days()` resolver (protocol mean =
    # AT-ADMISSION prediction). Route both through the canonical
    # resolver so the "予定入院期間" and "推定入院期間" slots of the
    # same document quote the same value. The resolver falls back to
    # `ctx.los_days` when disease_protocol is unavailable.
    los, _los_facts = generator._estimated_los_days(ctx)
    if los > 0:
        parts.append(t("ap_plan.estimated_los", lang, los=los))
    # The admission day's drugs, ranked by clinical priority (Issue #3247).
    from clinosim.modules.document.narrative._medication_plan import cap_names, ranked_medication_names

    _adm_raw = _o(getattr(ctx, "encounter", None), "admission_datetime", None)
    med_names = ranked_medication_names(ctx, day=0)
    if med_names:
        parts.append(t("ap_plan.initial_meds", lang, list=cap_names(med_names, lang)))
    # Ordered procedures (workup)
    # Admission-day procedures, named from their codes (Issue #3246); a
    # later operation is not yet done when the H&P is written.
    procs = procedure_names(ctx.procedures, lang, admission=_adm_raw, day=0)[:4]
    if procs:
        sep = t("list_sep.serial", lang)
        parts.append(t("ap_plan.workup_procedures", lang, list=sep.join(procs)))
    parts.extend(admission_order_items(ctx))
    parts.extend(admission_plan_items(ctx))
    if not parts:
        parts.append(t("ap_plan.observation_fallback", lang))
    return t("list_sep.chunk", lang).join(parts)


_ADMISSION_ORDER_SETS = ("admission_initial", "admission_care")
_MAX_LABS, _MAX_IMAGING, _MAX_SUPPORTIVE = 8, 4, 6


def admission_order_items(ctx: NarrativeContext) -> list[str]:
    """The admission's initial work-up and supportive care / monitoring from
    the CIF orders of the admission order sets (Issue #3245): the lab panels
    and imaging studies ordered, then the therapy and procedure orders (diet,
    oxygen, monitoring, VTE prophylaxis, ...), each named in the note language.
    The drugs are written by ``ap_plan.initial_meds``. ``[]`` for an admission
    with no such orders."""
    from clinosim.locale.free_text import localize_procedure_name
    from clinosim.locale.loader import imaging_exam_display, lab_display

    lang = ctx.target_lang
    enc_id = str(_o(ctx.encounter, "encounter_id", "") or "") if ctx.encounter is not None else ""
    labs: list[str] = []
    imaging: list[str] = []
    supportive: list[str] = []
    for order in ctx.orders or []:
        if (_o(order, "order_set", "") or "") not in _ADMISSION_ORDER_SETS:
            continue
        order_enc = str(_o(order, "encounter_id", "") or "")
        if enc_id and order_enc and order_enc != enc_id:
            continue
        otype = _o(order, "order_type", "") or ""
        kind = str(getattr(otype, "value", otype)).lower()
        raw = str(_o(order, "display_name", "") or "")
        if kind == "lab":
            name = lab_display(str(_o(order, "panel_key", "") or raw), lang)
            if name and name not in labs:
                labs.append(name)
        elif kind == "imaging":
            name = imaging_exam_display(raw, lang)
            if name and name not in imaging:
                imaging.append(name)
        elif kind in ("therapy", "procedure") and raw:
            name = localize_procedure_name(raw, lang)
            if name and name not in supportive:
                supportive.append(name)
    sep = t("list_sep.serial", lang)
    items: list[str] = []
    if labs or imaging:
        listed = [*labs[:_MAX_LABS], *imaging[:_MAX_IMAGING]]
        items.append(t("ap_plan.initial_workup", lang, list=sep.join(listed)))
    if supportive:
        items.append(t("ap_plan.supportive_care", lang, list=sep.join(supportive[:_MAX_SUPPORTIVE])))
    return items


def admission_plan_items(ctx: NarrativeContext) -> list[str]:
    """The problem-specific items of the admission plan (Issue #3245): the
    operation an admission for a surgical disease plans (the disease protocol's
    ``requires_surgery``, named from the stay's operation record) and the
    code status the record assigned. Nothing is written for a problem the
    record gives no basis for."""
    from clinosim.codes import display as registry_display
    from clinosim.modules.document.narrative.renderers._shared_helpers import (
        primary_surgical_procedure,
        procedure_prose_name,
    )

    lang = ctx.target_lang
    items: list[str] = []
    if ctx.disease_protocol is not None and bool(_o(ctx.disease_protocol, "requires_surgery", False)):
        surgery = primary_surgical_procedure(ctx)
        name = procedure_prose_name(surgery, lang) if surgery is not None else ""
        if name:
            items.append(t("ap_plan.planned_surgery", lang, name=name))
    status = registry_display("snomed-ct", ctx.code_status, lang) if ctx.code_status else ""
    if status:
        items.append(t("ap_plan.code_status", lang, status=status))
    return items
