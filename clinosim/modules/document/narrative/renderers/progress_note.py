"""Progress note (PROGRESS_NOTE / SOAP) narrative renderer.

Extracted verbatim from
``template_generator.TemplateNarrativeGenerator._render_progress_note_text``
as step C1b of the full-review Phase C renderer split (CRITICAL C1).
Behavior is byte-identical — the class method is now a thin delegator.

Unlike the B8/C1a pilots (ed_triage_note, nursing_shift_note), this
renderer calls several composer methods on the generator instance
(``_compose_progress_subjective_from_state`` etc.). To keep the pattern
free-standing, ``render_progress_note`` accepts ``generator`` as its
first argument and delegates composer calls back to it. Later refactors
can lift composers out of the class one at a time; the signature here
makes that migration path explicit.
"""

from __future__ import annotations

from copy import copy
from typing import TYPE_CHECKING

from clinosim.countries import has_authored_narrative
from clinosim.locale.i18n import t
from clinosim.locale.loader import narrative_label as _label
from clinosim.modules.document.narrative._progress_exam import (
    agreeing_clauses,
    coma_avpu,
    period_states,
    progress_exam_findings,
    unchanged_systems,
    worst_avpu,
)
from clinosim.modules.document.narrative._template_helpers import (
    _render_safety_skips_line,
)
from clinosim.modules.document.narrative.registry import DocumentTypeSpec
from clinosim.modules.document.narrative.renderers._composers import (
    _complications_known_on_day,
    _note_period_vitals,
    apply_cc_pe_consistency,
    pe_vitals_reading,
)
from clinosim.modules.document.narrative.renderers._disease_exam import exam_findings
from clinosim.modules.document.narrative.renderers._exam_agreement import arrival_vital_states
from clinosim.types.document import NarrativeContext, NarrativeOutput

if TYPE_CHECKING:
    from clinosim.modules.document.narrative.template_generator import (
        TemplateNarrativeGenerator,
    )


def render_progress_note(
    generator: TemplateNarrativeGenerator, ctx: NarrativeContext, spec: DocumentTypeSpec
) -> NarrativeOutput:
    """Build a SOAP-style progress note as plain text (PROGRESS_NOTE)."""
    facts: list[str] = []
    lang = ctx.target_lang
    soap_labels = tuple(_label("soap_label", slug, lang) for slug in ("subjective", "objective", "assessment", "plan"))

    # daily_trajectory / physical_exam_findings values (disease YAML +
    # reference_data) are JP-only strings. The EN locale must not read
    # the JP source directly — instead synthesize English SOAP text
    # from CIF facts (chronic conditions, abnormal labs, active meds,
    # complications). Issue #1074 B9 (session 99): EN branch now uses
    # ``_compose_progress_assessment_from_state`` /
    # ``_compose_progress_plan_from_state`` state-composers which
    # produce patient-specific per-day text instead of the generic
    # fallback (baseline: 19.4 % ``Clinical assessment ongoing`` +
    # 7.8 % ``Continue current management`` across 1,409 progress
    # notes at US p=2000 seed=500).
    if not has_authored_narrative(lang):
        facts.append("composed:progress_note_soap_en")
        # Issue #1155 (session-103): subjective + objective previously
        # short-circuited to "No special findings" on every EN
        # inpatient progress note. Now use the CIF-derived composers
        # (subjective covers hospital day / fever / desat; objective
        # uses today's vitals line already known to be locale-neutral).
        # Issues #3235 / #3247: the same period summary (latest values,
        # abnormal extremes, oxygen) as the JA Objective.
        composed_subj = generator._compose_progress_subjective_from_state(ctx)
        _obj_vitals = generator._compose_today_vitals_line(ctx)
        subjective = composed_subj or t("fallback.generic_fallback", lang)
        objective = _obj_vitals if _obj_vitals else t("fallback.generic_fallback", lang)
        if composed_subj:
            facts.append("ctx.progress_subjective.state_composed.en")
        if _obj_vitals:
            facts.append(f"ctx.vitals[day_{ctx.day_index}].en")
        # Assessment + plan now use the state-composers so each day of
        # each encounter carries patient-specific reasoning.
        composed_assess = generator._compose_progress_assessment_from_state(ctx)
        composed_plan = generator._compose_progress_plan_from_state(ctx)
        assessment = composed_assess or t("fallback.generic_assessment", lang)
        plan = composed_plan or t("fallback.generic_plan", lang)
        if composed_assess:
            facts.append("ctx.progress_assessment.state_composed.en")
        if composed_plan:
            facts.append("ctx.progress_plan.state_composed.en")
    else:
        # Resolve daily trajectory for this day (with fallback chain)
        traj, traj_source = generator._resolve_daily_trajectory_with_source(
            ctx, ctx.clinical_course_archetype, ctx.day_index
        )
        if traj_source:
            facts.append(traj_source)

        _generic_s = t("fallback.generic_fallback", lang)
        _generic_a = t("fallback.generic_assessment", lang)
        _generic_p = t("fallback.generic_plan", lang)
        # v9 (2026-08-17) density fix: _resolve_daily_trajectory_with_source
        # returns a placeholder dict (「特記事項なし」/「経過観察中」/「治療
        # 継続」) when the disease YAML has no daily_trajectory. Treat those
        # placeholders as if the value were absent so the state-composers
        # can inject CIF-derived content instead of a 6-char fallback
        # winning silently.
        _placeholders = {_generic_s, _generic_a, _generic_p, ""}

        def _prefer(traj_value: str | None, composed: str, generic: str) -> str:
            if traj_value and traj_value not in _placeholders:
                return traj_value
            return composed or generic

        subjective = _prefer(traj.get("subjective"), generator._compose_progress_subjective_from_state(ctx), _generic_s)
        _obj_raw = traj.get("objective")
        objective = _obj_raw if (_obj_raw and _obj_raw not in _placeholders) else ""
        assessment = _prefer(traj.get("assessment"), generator._compose_progress_assessment_from_state(ctx), _generic_a)
        composed_plan_ja = generator._compose_progress_plan_from_state(ctx)
        plan = _prefer(traj.get("plan"), composed_plan_ja, _generic_p)
        # Issue #2981: an authored trajectory plan lists no drugs, so a drug
        # held today (hyperkalemia hold) is added to it.
        if plan != composed_plan_ja:
            from clinosim.modules.document.narrative.renderers._composers import compose_progress_held_line

            held_line = compose_progress_held_line(ctx)
            if held_line:
                base = plan.rstrip().removesuffix(t("list_sep.period", lang))
                plan = f"{base}{t('list_sep.period_space', lang)}{held_line}"

        # v6 blocker fix (2026-08-16): prepend today's numeric vitals
        # snapshot to `objective` for inpatient progress_note. `objective`
        # is by-design non-LLM (see progress_note spec), so the template
        # itself must carry per-day BP/HR/RR/SpO2/T; otherwise it collapses
        # to a static disease_YAML string across all days of a stay.
        today_vitals_line = generator._compose_today_vitals_line(ctx)
        # Issue #3235: the objective text, the general state and the exam follow
        # the readings of the note's period.
        readings = _note_period_vitals(ctx)
        prev_period = _note_period_vitals(ctx, previous=True)
        states = period_states(ctx, readings, prev_period)
        objective = agreeing_clauses(objective, states, lang)
        if today_vitals_line:
            facts.append("ctx.vitals.today")
            objective = f"{today_vitals_line}。{objective}" if objective else today_vitals_line

        # Add physical exam findings to the objective section (JP only,
        # EN skips to prevent CJK leak — sibling of build_physical_examination fix)
        # Issue #3227: the same disease exam as the H&P (the AF rhythm and the
        # stroke deficit included), not the archetype baseline alone.
        # Issue #3235: evaluated for the note's day, the clauses the period's
        # vital signs contradict are left out and its abnormal readings added.
        reading = pe_vitals_reading(ctx)
        phys_exam, exam_source = exam_findings(
            generator, ctx, reading, arrival_vital_states(reading, ctx) if reading is not None else {}
        )
        if exam_source:
            facts.append(exam_source)
        findings = (
            progress_exam_findings(ctx, readings, phys_exam, str(ctx.severity or ""), lang, prev_period)
            if phys_exam
            else {}
        )
        # Issue #3235: a system whose exam is the previous day's word for word
        # is stated as unchanged instead of repeated.
        unchanged: list[str] = []
        if findings and ctx.day_index >= 1:
            prev_ctx = copy(ctx)
            prev_ctx.day_index = ctx.day_index - 1
            prev_readings = prev_period
            prev_reading = pe_vitals_reading(prev_ctx)
            prev_phys, _ = exam_findings(
                generator,
                prev_ctx,
                prev_reading,
                arrival_vital_states(prev_reading, prev_ctx) if prev_reading is not None else {},
            )
            prev_findings = (
                progress_exam_findings(ctx, prev_readings, prev_phys, str(ctx.severity or ""), lang)
                if prev_phys
                else {}
            )
            # Issue #3544: nothing is "unchanged" in a period with a new
            # complication, and a comatose patient's neurological exam is stated.
            new_comps, _ongoing = _complications_known_on_day(ctx, getattr(ctx, "authored_datetime", None))
            unchanged = unchanged_systems(
                findings,
                prev_findings,
                worst_avpu(readings) != worst_avpu(prev_readings),
                new_in_period=bool(new_comps),
                coma=bool(coma_avpu(readings)),
            )
        phys_summary = generator._format_physical_exam(
            {k: v for k, v in findings.items() if k not in unchanged}, ctx.severity, lang
        )
        # Issue #2086: the consciousness clause follows the day's AVPU. The
        # admission chief-complaint rewrites (altered consciousness, severe
        # dyspnea) belong to the admission exam, not to every later day.
        if phys_summary:
            phys_summary, pe_facts = apply_cc_pe_consistency(phys_summary, ctx, use_chief_complaint=False)
            facts.extend(pe_facts)
        if unchanged:
            if len(unchanged) == len(findings):
                same = t("progress.exam_all_unchanged", lang)
            else:
                names = [_label("body_system", system, lang, fallback=system) for system in unchanged]
                same = t("progress.exam_unchanged", lang, systems=t("list_sep.serial", lang).join(names))
            phys_summary = f"{phys_summary}{t('list_sep.period_space', lang)}{same}" if phys_summary else same
            facts.append("ctx.exam.unchanged_from_previous_day")
        if phys_summary:
            objective = f"{objective}。{phys_summary}" if objective else phys_summary
        # Issue #3456: the "no special findings" filler states an empty
        # section; it is not written before or beside a finding.
        objective = objective or _generic_s

    # Issue #1066 (drug_safety): append avoidance-and-substitution
    # reasoning to plan when this encounter carries safety_skip_log
    # entries. Same content flows into the LLM prompt via Task 10/11.
    # Issue #3411: the in-stay events, one hold per drug, none of a drug the
    # day's medication record already lists as held.
    from clinosim.modules.document.narrative._medication_plan import note_medications
    from clinosim.modules.document.narrative._safety_skips import progress_note_safety_skips

    skips_addendum = _render_safety_skips_line(
        progress_note_safety_skips(getattr(ctx, "safety_skips", None) or [], note_medications(ctx).held_refs), lang
    )
    if skips_addendum:
        plan = f"{plan}\n{skips_addendum}" if plan else skips_addendum
        facts.append("ctx.safety_skips")

    # Build SOAP note. Also populate `sections` so the section-level LLM
    # replacement pipeline can operate on progress_note (session 88j
    # Tier 1 uplift). `raw_text_rejoin` metadata carries the label /
    # section pairs so `_apply_template_seed_strategy` can rebuild
    # `raw_text` from the possibly-replaced sections for FREE_TEXT
    # documents (DocumentReference emit reads `raw_text`, not sections).
    sep = "\n"
    section_order = [
        (soap_labels[0], "subjective", subjective),
        (soap_labels[1], "objective", objective),
        (soap_labels[2], "assessment", assessment),
        (soap_labels[3], "plan", plan),
    ]
    sections = {key: body for _, key, body in section_order}
    raw_text = sep.join(f"{label} {body}" for label, _, body in section_order)

    # Always add at least ctx reference
    facts.append("ctx.day_index")
    facts.append("ctx.clinical_course_archetype")

    return NarrativeOutput(
        raw_text=raw_text,
        sections=sections,
        metadata={
            "generator": "template",
            "lang": lang,
            "day_index": ctx.day_index,
            "raw_text_rejoin": {
                "separator": sep,
                # ordered list of (label, section_key) so the post-LLM
                # rejoin preserves S / O / A / P sequence + labels.
                "order": [(label, key) for label, key, _ in section_order],
            },
        },
        facts_used=facts,
    )
