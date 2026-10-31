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

from clinosim.codes import display as registry_display
from clinosim.locale.i18n import t
from clinosim.modules._shared import get_attr_or_key as _o
from clinosim.modules.document.narrative._localization import _localize_complication
from clinosim.modules.document.narrative._narrative_utils import _parse_iso_datetime
from clinosim.modules.document.narrative._template_helpers import (
    _GENERIC_ASSESSMENT_EN,
    _GENERIC_ASSESSMENT_JA,
    _GENERIC_PLAN_EN,
    _GENERIC_PLAN_JA,
    _label,
)
from clinosim.types.document import NarrativeContext

if TYPE_CHECKING:
    from clinosim.modules.document.narrative.template_generator import (
        TemplateNarrativeGenerator,
    )


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
    if lang != "ja":
        facts.append("composed:cif_state_en")
        _en_assessment = _compose_ap_assessment_from_state(ctx) or _GENERIC_ASSESSMENT_EN
        _en_plan = _compose_ap_plan_from_state(generator, ctx) or _GENERIC_PLAN_EN
        return f"Assessment: {_en_assessment} Plan: {_en_plan}", facts

    traj, traj_src = generator._resolve_daily_trajectory_with_source(ctx, ctx.clinical_course_archetype, 0)
    if traj_src:
        facts.append(traj_src)

    _generic_a = _GENERIC_ASSESSMENT_JA
    _generic_p = _GENERIC_PLAN_JA
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
    plan = (
        traj_p
        if (traj_p and traj_p not in _placeholders)
        else (_compose_ap_plan_from_state(generator, ctx) or _generic_p)
    )
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
            if _sev and lang == "ja":
                from clinosim.modules.document.narrative.replacement_strategy import (
                    _localize_severity_ja,
                )

                _sev = _localize_severity_ja(_sev)
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
    conds = _o(ctx.patient, "chronic_conditions", []) or [] if ctx.patient else []
    if conds:
        from clinosim.modules.output.fhir_r4.lib.common import (
            map_diagnosis_code as _map_diagnosis_code,
        )

        country = "JP" if ctx.locale.lower() == "jp" else "US"
        key = _label("code_system_icd_display", "primary", lang)

        def _resolve_chronic_label(c: object) -> str:
            base = _o(c, "code", "") or ""
            if not base:
                return ""
            emit = _map_diagnosis_code(base, country) or base
            return registry_display(key, emit, lang) or emit

        labels = [_resolve_chronic_label(c) for c in conds[:4]]
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
    # actual observed LOS) while `_build_acp_estimated_los` used the
    # canonical `_estimated_los_days()` resolver (protocol mean =
    # AT-ADMISSION prediction). Route both through the canonical
    # resolver so the "予定入院期間" and "推定入院期間" slots of the
    # same document quote the same value. The resolver falls back to
    # `ctx.los_days` when disease_protocol is unavailable.
    los, _los_facts = generator._estimated_los_days(ctx)
    if los > 0:
        parts.append(t("ap_plan.estimated_los", lang, los=los))
    # Today's meds (day 0 admission-day filter). Same explicit-day-else-
    # timestamp-derived pattern as `_compose_progress_plan_from_state`
    # (Issue #1154) so real CIF MedicationAdministration without a
    # ``day`` field still filters correctly.
    _adm_raw = _o(getattr(ctx, "encounter", None), "admission_datetime", None)
    _adm_dt = _parse_iso_datetime(_adm_raw) if _adm_raw is not None else None
    admins = list(ctx.medications or [])
    med_names: list[str] = []
    seen: set[str] = set()
    for m in admins[:60]:
        d = _o(m, "day", None)
        if d is None and _adm_dt is not None:
            _mts_raw = _o(m, "actual_datetime", None) or _o(m, "scheduled_datetime", None)
            _mts = _parse_iso_datetime(_mts_raw) if _mts_raw is not None else None
            if _mts is not None:
                # Session-104 Issue #1166: calendar-day bucket
                # (sibling of _filter_vitals_for_day v7).
                d = (_mts.date() - _adm_dt.date()).days
        if d is not None and d != 0:  # admission day
            continue
        name = _o(m, "drug_name", None) or _o(m, "medication", None)
        if not name or name in seen:
            continue
        seen.add(name)
        # Drug-name katakana lookup is a JA-locale-specific data
        # pipeline via `localize_drug_name(name, lang)` — a no-op
        # for any lang without a lookup table (today: any non-`"ja"`).
        # Adding a new locale is a data-only extension of
        # `drug_names_<lang>.yaml`; no branch here.
        from clinosim.modules.output.fhir_r4.lib.localization import localize_drug_name

        med_names.append(localize_drug_name(str(name), lang))
        if len(med_names) >= 6:
            break
    if med_names:
        sep = t("list_sep.serial", lang)
        parts.append(t("ap_plan.initial_meds", lang, list=sep.join(med_names)))
    # Ordered procedures (workup)
    procs = [_o(pr, "procedure_name", None) or _o(pr, "name", None) for pr in (ctx.procedures or [])[:4]]
    procs = [p for p in procs if p]
    if procs:
        sep = t("list_sep.serial", lang)
        parts.append(t("ap_plan.workup_procedures", lang, list=sep.join(str(p) for p in procs)))
    if not parts:
        parts.append(t("ap_plan.observation_fallback", lang))
    return t("list_sep.chunk", lang).join(parts)
