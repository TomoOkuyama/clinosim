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

from typing import TYPE_CHECKING

from clinosim.modules.document.narrative._template_helpers import (
    _GENERIC_ASSESSMENT_EN,
    _GENERIC_ASSESSMENT_JA,
    _GENERIC_FALLBACK_EN,
    _GENERIC_FALLBACK_JA,
    _GENERIC_PLAN_EN,
    _GENERIC_PLAN_JA,
    _label,
    _render_safety_skips_line,
)
from clinosim.modules.document.narrative.registry import DocumentTypeSpec
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
    if lang != "ja":
        facts.append("composed:progress_note_soap_en")
        # Issue #1155 (session-103): subjective + objective previously
        # short-circuited to "No special findings" on every EN
        # inpatient progress note. Now use the CIF-derived composers
        # (subjective covers hospital day / fever / desat; objective
        # uses today's vitals line already known to be locale-neutral).
        composed_subj = generator._compose_progress_subjective_from_state(ctx)
        _obj_vitals = generator._compose_pe_vitals_line(ctx)
        subjective = composed_subj or _GENERIC_FALLBACK_EN
        objective = _obj_vitals if _obj_vitals else _GENERIC_FALLBACK_EN
        if composed_subj:
            facts.append("ctx.progress_subjective.state_composed.en")
        if _obj_vitals:
            facts.append(f"ctx.vitals[day_{ctx.day_index}].en")
        # Assessment + plan now use the state-composers so each day of
        # each encounter carries patient-specific reasoning.
        composed_assess = generator._compose_progress_assessment_from_state(ctx)
        composed_plan = generator._compose_progress_plan_from_state(ctx)
        assessment = composed_assess or _GENERIC_ASSESSMENT_EN
        plan = composed_plan or _GENERIC_PLAN_EN
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

        _generic_s = _GENERIC_FALLBACK_JA
        _generic_a = _GENERIC_ASSESSMENT_JA
        _generic_p = _GENERIC_PLAN_JA
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
        objective = _obj_raw if (_obj_raw and _obj_raw not in _placeholders) else _generic_s
        assessment = _prefer(traj.get("assessment"), generator._compose_progress_assessment_from_state(ctx), _generic_a)
        plan = _prefer(traj.get("plan"), generator._compose_progress_plan_from_state(ctx), _generic_p)

        # v6 blocker fix (2026-08-16): prepend today's numeric vitals
        # snapshot to `objective` for inpatient progress_note. `objective`
        # is by-design non-LLM (see progress_note spec), so the template
        # itself must carry per-day BP/HR/RR/SpO2/T; otherwise it collapses
        # to a static disease_YAML string across all days of a stay.
        today_vitals_line = generator._compose_today_vitals_line(ctx)
        if today_vitals_line:
            facts.append("ctx.vitals.today")
            objective = f"{today_vitals_line}。{objective}"

        # Add physical exam findings to the objective section (JP only,
        # EN skips to prevent CJK leak — sibling of _build_physical_examination fix)
        phys_exam = generator._resolve_physical_exam(ctx, ctx.clinical_course_archetype, ctx.day_index)
        if phys_exam:
            facts.append(f"physical_exam_findings.{ctx.clinical_course_archetype}.day_{ctx.day_index}")
        phys_summary = generator._format_physical_exam(phys_exam, ctx.severity, lang)
        # Issue #2086: same consciousness / CC consistency rewrite as the H&P PE.
        if phys_summary:
            phys_summary, pe_facts = generator._apply_cc_pe_consistency(phys_summary, ctx)
            facts.extend(pe_facts)
        if phys_summary:
            objective = f"{objective}。{phys_summary}"

    # Issue #1066 (drug_safety): append avoidance-and-substitution
    # reasoning to plan when this encounter carries safety_skip_log
    # entries. Same content flows into the LLM prompt via Task 10/11.
    skips_addendum = _render_safety_skips_line(getattr(ctx, "safety_skips", None) or [], lang)
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
