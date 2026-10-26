"""ED helper cluster — small context accessors used by the ED_NOTE
section builders and by chief_complaint / HPI's ED-note branches.

Extracted from ``template_generator.TemplateNarrativeGenerator`` as step
C1r of the full-review Phase C renderer split (CRITICAL C1). Behavior is
byte-identical — the three class methods are now thin delegators.

The helpers depend only on ``ctx`` plus module-level reference data; no
helper here dispatches back to the class, so no ``generator`` threading.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from clinosim.locale.i18n import t
from clinosim.modules._shared import get_attr_or_key as _o
from clinosim.modules.document.narrative._template_helpers import _label

if TYPE_CHECKING:
    from clinosim.types.document import NarrativeContext


def get_ed_note_template(ctx: NarrativeContext) -> Any | None:
    """Extract ed_note_template from encounter_protocol (or None)."""
    ep = ctx.encounter_protocol
    if ep is None:
        return None
    narrative = _o(ep, "narrative", None)
    if narrative is None:
        return None
    return _o(narrative, "ed_note_template", None)


def ed_triage_level(ctx: NarrativeContext) -> str:
    """Extract the JTAS triage level (1-5) from the encounter, or "N/A".

    Encounters that skipped triage_enricher (test fixtures, non-JP
    cohorts pre-#941) leave ``triage_data`` unset; falls back to a
    severity → JTAS mapping so the disposition line still carries an
    integer rather than blank.
    """
    enc = ctx.encounter
    if enc is None:
        return "-"
    triage = _o(enc, "triage_data", None)
    if triage is not None:
        level = _o(triage, "level", "") or ""
        if level:
            return str(level)
    severity = str(_o(enc, "severity", "") or ctx.severity or "").lower()
    return {"severe": "2", "moderate": "3", "mild": "4"}.get(severity, "-")


def ed_disposition_reason(ctx: NarrativeContext, lang: str) -> str:
    """Return a short reasoning phrase (admit dx / CC / acuity) for #981.

    Never returns empty — an empty reason would collapse the
    parenthetical to "（）" and read worse than the pre-fix bare
    disposition. Fall-through priority:

      1. ``encounter.chief_complaint_<lang>`` / ``chief_complaint`` –
         the specific complaint the ED chart already knows about.
      2. ``disease_protocol.chief_complaint`` – matches when the
         encounter did not override.
      3. ``encounter.severity`` / ``ctx.severity`` acuity keyword.
      4. Locale-appropriate generic ("症状に応じて対応" / "clinical
         judgment").
    """
    from clinosim.locale.loader import resolve_localized_display

    enc = ctx.encounter
    if enc is not None:
        preferred_key = f"chief_complaint_{lang}"
        cc = _o(enc, preferred_key, "") or _o(enc, "chief_complaint", "")
        if cc:
            return str(cc)
    if ctx.disease_protocol is not None:
        proto_cc = _o(ctx.disease_protocol, "chief_complaint", None)
        if isinstance(proto_cc, dict):
            val = resolve_localized_display(proto_cc, lang, fallback="")
            if val:
                return str(val)
        elif proto_cc:
            return str(proto_cc)
    severity = str(_o(enc, "severity", "") or ctx.severity or "").lower() if enc is not None else ""
    acuity_label = _label("ed_acuity_reason", severity, lang, fallback="")
    if acuity_label:
        return acuity_label
    return t("control_status.clinical_judgment", lang)
