"""One phrasing of drug-safety events for the template and LLM paths
(Issue #2519).

A safety-skip entry records a drug that was considered but avoided, held,
substituted, switched or de-escalated. The deterministic template renders it
in the plan section (``safety_skips.*`` phrases); the LLM prompt receives the
same facts as a leading-marker bullet (``safety_skips_prompt.*`` phrases).
Both read the event the same way through :func:`safety_skip_line`.
"""

from __future__ import annotations

from collections.abc import Callable

from clinosim.locale.i18n import t
from clinosim.locale.localized import localized_field

__all__ = ["safety_skip_line"]

# event_type -> phrase-key stem; an absent or unknown event is the legacy
# pair-conflict avoidance (Issue #1403).
_EVENT_STEMS = {
    "hold": "hold",
    "substitute": "substitute",
    "switch": "switch",
    "deescalate": "deescalate",
}
_EVENTS_WITHOUT_SUBSTITUTE_VARIANT = frozenset({"hold"})


def safety_skip_line(
    skip: dict,
    lang: str,
    *,
    prefix: str,
    drug_name: Callable[[str], str] | None = None,
) -> str:
    """The sentence for one safety-skip entry under the ``prefix`` phrase set
    (``"safety_skips"`` or ``"safety_skips_prompt"``). ``drug_name`` maps a
    drug name to its display form (the template path's katakana
    localization); identity when None."""
    event = str(skip.get("event_type") or "avoid").lower()
    stem = _EVENT_STEMS.get(event, "avoid")
    if stem == "avoid" and skip.get("conflict_kind") == "allergy":
        # Issue #2930: an allergy is not a co-administration conflict.
        stem = "avoid_allergy"
    localize = drug_name or (lambda name: name)
    considered = localize(localized_field(skip, "considered", lang))
    # Issue #2992: the phrase supplies the sentence's own full stop, so a
    # reason written as a sentence does not end in "..".
    conflict = localized_field(skip, "avoided_due_to", lang).rstrip(" .。")
    substituted = localize(localized_field(skip, "substituted_with", lang))
    day = skip.get("stopped_on_day")
    day_phrase = (
        t("safety_skips.day_phrase_specific", lang, day=int(day)) if day else t("safety_skips.day_phrase_default", lang)
    )
    if stem in _EVENTS_WITHOUT_SUBSTITUTE_VARIANT:
        key = f"{prefix}.{stem}"
    else:
        key = f"{prefix}.{stem}_with_sub" if substituted else f"{prefix}.{stem}_no_sub"
    return t(key, lang, considered=considered, conflict=conflict, substituted=substituted, day_phrase=day_phrase)
