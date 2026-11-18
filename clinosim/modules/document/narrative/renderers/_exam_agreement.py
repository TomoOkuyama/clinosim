"""Agreement of an authored exam text with the vital-sign reading a note quotes
(Issues #3243, #3245).

An exam is written per disease and severity, not from the patient's readings,
so a clause that states a vital sign ("tachycardia", "hypotension",
"tachypnea") is left out when the reading contradicts it. The terms and
limits are those of ``ed_note_admitted.yaml``.
"""

from __future__ import annotations

from typing import Any

from clinosim.locale.localized import normalize_lang
from clinosim.modules._shared import get_attr_or_key as _o
from clinosim.modules.document.reference_data_loaders import load_ed_note_admitted
from clinosim.modules.observation.pediatric_ranges import age_in_completed_months, pediatric_vital_range
from clinosim.types.document import NarrativeContext

__all__ = ["agreeing_clauses", "arrival_vital_states"]


def arrival_vital_states(arrival: Any, ctx: NarrativeContext) -> dict[str, str]:
    """``{vital: "low" | "normal" | "high"}`` of the arrival reading, judged
    against a child's age-banded range where one lists the vital, else the
    adult limits of ``ed_note_admitted.yaml``. A vital without a value is
    left out."""
    limits = load_ed_note_admitted().adult_vital_limits
    age_months = age_in_completed_months(_o(ctx.patient, "date_of_birth", None), _o(arrival, "timestamp", None))
    states: dict[str, str] = {}
    for vital, adult in limits.items():
        value = _o(arrival, vital, None)
        if value is None:
            continue
        child = pediatric_vital_range(vital, age_months)
        low, high = (child.low, child.high) if child is not None else (adult.low, adult.high)
        if low is not None and float(value) < low:
            states[vital] = "low"
        elif high is not None and float(value) > high:
            states[vital] = "high"
        else:
            states[vital] = "normal"
    return states


def agreeing_clauses(text: str, states: dict[str, str], lang: str) -> str:
    """``text`` without the clauses whose vital-sign statement the arrival
    reading contradicts (``ed_note_admitted.yaml::exam_vital_terms``)."""
    if not text:
        return ""
    data = load_ed_note_admitted()
    code = normalize_lang(lang)
    separators = data.clause_separators.get(code) or data.clause_separators["en"]
    terms = sorted(
        ((term, entry) for entry in data.exam_vital_terms for term in entry.terms.get(code) or entry.terms["en"]),
        key=lambda pair: -len(pair[0]),
    )

    def agrees(clause: str) -> bool:
        stated: dict[str, set[str]] = {}
        rest = clause.lower()
        for term, entry in terms:
            if term.lower() in rest:
                rest = rest.replace(term.lower(), " ")
                stated.setdefault(entry.vital, set()).update(entry.states)
        return all(vital not in states or states[vital] in ok for vital, ok in stated.items())

    def keep(piece: str, level: int) -> str:
        if level == len(separators):
            return piece if agrees(piece) else ""
        sep = separators[level]
        return sep.join(kept for kept in (keep(part, level + 1) for part in piece.split(sep)) if kept)

    return keep(text, 0)
