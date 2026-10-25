"""ED triage note (ED_TRIAGE_NOTE) narrative renderer.

Extracted verbatim from
``template_generator.TemplateNarrativeGenerator._render_ed_triage_note_text``
as the pilot of the full-review Phase B8 renderer split (CRITICAL C1).
The behavior is byte-identical — the method inside the class is now a
thin delegator to this free-standing function.

Reads ``TriageData`` fields (level, level_system, arrival_mode,
chief_complaint_summary) from ``ctx.encounter.triage_data``.
Gracefully falls back to a generic phrase when ``triage_data`` is None.
"""

from __future__ import annotations

from clinosim.locale.i18n import t
from clinosim.modules._shared import get_attr_or_key as _o
from clinosim.modules.document.narrative._template_helpers import _label
from clinosim.modules.document.narrative.registry import DocumentTypeSpec
from clinosim.types.document import NarrativeContext, NarrativeOutput


def render_ed_triage_note(ctx: NarrativeContext, spec: DocumentTypeSpec) -> NarrativeOutput:
    """Build ED_TRIAGE_NOTE as free text from encounter.triage_data.

    EN locale note: arrival_mode and chief_complaint_summary from CIF are
    used directly; level_system labels (ESI/JTAS) are system codes (no
    translation needed). EN output uses the same field values but with
    English grammatical framing.
    """
    facts: list[str] = []
    lang = ctx.target_lang

    triage = _o(ctx.encounter, "triage_data", None)

    if triage is None:
        raw_text = t("fallback.triage_fallback", lang)
        return NarrativeOutput(
            raw_text=raw_text,
            metadata={"generator": "template", "lang": lang},
            facts_used=facts,
        )

    facts.append("encounter.triage_data")

    level = _o(triage, "level", "") or ""
    level_system = _o(triage, "level_system", "") or ""
    arrival_mode = _o(triage, "arrival_mode", "") or ""
    cc_summary = _o(triage, "chief_complaint_summary", "") or ""
    arrival_display = _label("arrival_mode", arrival_mode, lang, fallback=arrival_mode)

    level_line = (
        t("triage_note.level_line_with_data", lang, system=level_system, level=level)
        if level_system and level
        else t("triage_note.level_line_none", lang)
    )
    arrival_line = (
        t("triage_note.arrival_line", lang, mode=arrival_display)
        if arrival_display
        else t("triage_note.arrival_line_none", lang)
    )
    cc_line = t("triage_note.cc_line", lang, cc=cc_summary) if cc_summary else t("triage_note.cc_line_none", lang)
    raw_text = "\n".join([level_line, arrival_line, cc_line])

    return NarrativeOutput(
        raw_text=raw_text,
        metadata={"generator": "template", "lang": lang},
        facts_used=facts,
    )
