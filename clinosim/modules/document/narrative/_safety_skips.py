"""One phrasing of drug-safety events for the template and LLM paths
(Issue #2519).

A safety-skip entry records a drug that was considered but avoided, held,
substituted, switched or de-escalated. The deterministic template renders it
in the plan section (``safety_skips.*`` phrases); the LLM prompt receives the
same facts as a leading-marker bullet (``safety_skips_prompt.*`` phrases).
Both read the event the same way through :func:`safety_skip_line`.
"""

from __future__ import annotations

from collections.abc import Callable, Collection

from clinosim.codes.drugs import drug_key
from clinosim.locale.i18n import t
from clinosim.locale.loader import hold_reason_change
from clinosim.locale.localized import localized_field

__all__ = ["progress_note_safety_skips", "safety_skip_line"]

# event_type -> phrase-key stem; an absent or unknown event is the legacy
# pair-conflict avoidance (Issue #1403).
_EVENT_STEMS = {
    "hold": "hold",
    "substitute": "substitute",
    "switch": "switch",
    "deescalate": "deescalate",
}
_EVENTS_WITHOUT_SUBSTITUTE_VARIANT = frozenset({"hold"})
# conflict_kind -> phrase-key stem of an avoidance that is not a drug-drug
# conflict (the conflict is the allergy or the condition, not a drug).
_AVOID_KIND_STEMS = {"allergy": "avoid_allergy", "disease": "avoid_condition"}
# rule_id of the hold logged while writing the discharge prescription
# (``simulator/discharge_rx.py``): a decision about the prescription, not a
# hold during the stay.
_DISCHARGE_HOLD_RULE = "discharge-medication-hold"
# Issue #3458: only a rule of ``contraindicated`` severity is a contraindication;
# a drug-drug avoidance of a lower severity is an interaction risk.
_INTERACTION_SEVERITIES = frozenset({"minor", "moderate", "major"})


def _identity(name: object) -> str:
    """The drug identity of a name (``KCl`` and ``塩化カリウム`` are one drug),
    the lower-cased text itself for a reason that is not a drug."""
    text = str(name or "").strip()
    return drug_key(text) or text.lower()


def progress_note_safety_skips(skips: list[dict], held_refs: Collection[str] = ()) -> list[dict]:
    """The safety events a daily progress note's plan states (Issue #3411):
    the in-stay ones, one hold per drug and each other event once.

    A hold logged by the discharge prescription is left to the discharge
    documents; a drug is held once, by the first hold event (a protocol logs
    the admission hold and the discharge one for the same drug); and a drug
    the day's medication record already names as held (``held_refs``: drug
    keys) is not stated a second time, its record carrying the day's reason.
    """
    out: list[dict] = []
    held = set(held_refs)
    seen: set[tuple] = set()
    for skip in skips:
        if skip.get("rule_id") == _DISCHARGE_HOLD_RULE:
            continue
        # The same event logged twice (a candidate drug avoided for the same
        # reason on two orders, or one drug under two raw names; Issue #3458)
        # is stated once.
        same = (
            str(skip.get("event_type") or "avoid").lower(),
            _identity(skip.get("considered")),
            _identity(skip.get("avoided_due_to")),
            _identity(skip.get("substituted_with")),
        )
        if same in seen:
            continue
        seen.add(same)
        if str(skip.get("event_type") or "avoid").lower() == "hold":
            ref = drug_key(str(skip.get("considered") or ""))
            if ref in held:
                continue
            held.add(ref)
        out.append(skip)
    return out


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
    if stem == "avoid" and skip.get("conflict_kind") in _AVOID_KIND_STEMS:
        # Issue #2930: an allergy is not a co-administration conflict;
        # Issue #3283: neither is a condition.
        stem = _AVOID_KIND_STEMS[str(skip.get("conflict_kind"))]
    elif stem == "avoid" and str(skip.get("severity") or "").lower() in _INTERACTION_SEVERITIES:
        # Issue #3458: a major / moderate interaction is a risk, not a
        # contraindication; the wording follows the rule's severity. An entry
        # with no severity (an older log) keeps the legacy phrase.
        stem = "avoid_interaction"
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
    reason_key = str(skip.get("hold_reason_key") or "")
    change = hold_reason_change(reason_key, lang) if stem == "hold" and prefix == "safety_skips" else ""
    if change:
        # Issue #3411: the oral diuretic "held" at a heart-failure admission is
        # a route switch; the reason beside it is the clinical state.
        return t(
            f"{prefix}.change",
            lang,
            considered=considered,
            change=change,
            conflict=hold_reason_change(reason_key, lang, reason_text=True),
        )
    if stem in _EVENTS_WITHOUT_SUBSTITUTE_VARIANT:
        key = f"{prefix}.{stem}" if conflict or prefix != "safety_skips" else f"{prefix}.hold_no_reason"
    else:
        key = f"{prefix}.{stem}_with_sub" if substituted else f"{prefix}.{stem}_no_sub"
    return t(key, lang, considered=considered, conflict=conflict, substituted=substituted, day_phrase=day_phrase)
