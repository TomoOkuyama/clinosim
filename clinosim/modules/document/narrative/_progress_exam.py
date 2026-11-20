"""A daily progress note's exam, general state and course from the vital signs
of its period (Issues #3235, #3247).

The exam text of a progress note is the disease exam of the note's day (the
H&P's exam source, with the AF rhythm and the stroke deficit), written per
severity and not from the patient's readings.
:func:`progress_exam_findings` leaves out the clauses a reading of the note's
period contradicts and adds the abnormal readings the exam does not state
(``reference_data/progress_exam.yaml``); :func:`course_line` says whether the
abnormal states of the period grew or shrank against the previous period.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

from clinosim.datafiles import load_validated_yaml
from clinosim.locale.i18n import t
from clinosim.locale.localized import normalize_lang
from clinosim.modules._shared import get_attr_or_key as _o
from clinosim.modules.observation.pediatric_ranges import age_in_completed_months, pediatric_vital_range

if TYPE_CHECKING:
    from clinosim.types.document import NarrativeContext

__all__ = [
    "ProgressExamRules",
    "current_states",
    "spo2_low_override",
    "agreeing_clauses",
    "any_abnormal",
    "course_line",
    "period_states",
    "progress_exam_findings",
    "progress_exam_rules",
    "unchanged_systems",
    "worst_avpu",
]

_YAML = Path(__file__).resolve().parents[1] / "reference_data" / "progress_exam.yaml"
_State = Literal["low", "normal", "high"]
_PSEUDO_VITALS = ("on_oxygen", "consciousness")


def _has_english(value: dict[str, Any]) -> dict[str, Any]:
    if "en" not in value:
        raise ValueError("English text is required (the fallback language)")
    return value


_Localized = Annotated[dict[str, Any], AfterValidator(_has_english)]


class _Limit(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    low: float | None = None
    high: float | None = None
    high_inclusive: bool = False
    # Which edge of a child's age-banded range is the low limit: the band's
    # normal-range ``low``, or its ``critical_low`` (hypotension).
    child_low: Literal["low", "critical_low"] = "low"


class _LimitOverride(BaseModel):
    """A patient-specific replacement of a vital's ``low`` limit (the target
    range of a COPD patient), for the patients of ``disease_ids`` or with a
    chronic or encounter diagnosis starting with a ``chronic_code_prefixes``
    entry."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    vital: str
    low: float
    disease_ids: list[str] = Field(default_factory=list)
    chronic_code_prefixes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _has_condition(self) -> _LimitOverride:
        if not (self.disease_ids or self.chronic_code_prefixes):
            raise ValueError("progress_exam.yaml: a limit override needs disease_ids or chronic_code_prefixes")
        return self


class _ExtraTerm(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    vitals: list[str] = Field(min_length=1)
    agree: Literal["all", "any"]
    states: list[_State] = Field(min_length=1)
    terms: Annotated[dict[str, list[str]], AfterValidator(_has_english)]


class _StateFinding(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    vital: str
    state: _State
    system: str
    text: _Localized


class _CourseItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    vital: str
    state: _State
    name: _Localized


class ProgressExamRules(BaseModel):
    """``progress_exam.yaml`` (Issue #3235)."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    limits: dict[str, _Limit] = Field(min_length=1)
    limit_overrides: list[_LimitOverride] = Field(default_factory=list)
    clause_separators: Annotated[dict[str, list[str]], AfterValidator(_has_english)]
    extra_terms: list[_ExtraTerm]
    state_findings: list[_StateFinding]
    course_items: list[_CourseItem]

    @model_validator(mode="after")
    def _known_vitals_and_systems(self) -> ProgressExamRules:
        from clinosim.modules.document.narrative.renderers._shared_helpers import PHYSICAL_EXAM_SYSTEMS

        known = set(self.limits) | set(_PSEUDO_VITALS)
        named = {o.vital for o in self.limit_overrides}
        named |= {v for term in self.extra_terms for v in term.vitals}
        named |= {f.vital for f in self.state_findings} | {c.vital for c in self.course_items}
        if named - known:
            raise ValueError(f"progress_exam.yaml: vitals without a limit {sorted(named - known)}")
        bad = sorted({f.system for f in self.state_findings} - set(PHYSICAL_EXAM_SYSTEMS))
        if bad:
            raise ValueError(f"progress_exam.yaml: unknown exam systems {bad}")
        return self


@lru_cache(maxsize=1)
def progress_exam_rules() -> ProgressExamRules:
    """The vital limits, vital-stating terms and findings of a progress
    note's exam (``progress_exam.yaml``)."""
    return ProgressExamRules.model_validate(load_validated_yaml(_YAML, ProgressExamRules))


@dataclass(frozen=True)
class _Term:
    text: str
    vitals: tuple[str, ...]
    agree: str
    states: frozenset[str]


@lru_cache(maxsize=4)
def _terms(code: str) -> tuple[_Term, ...]:
    """Every vital-stating term of language ``code``, longest first: the
    single-vital terms of ``ed_note_admitted.yaml`` and the ``extra_terms``."""
    from clinosim.modules.document.reference_data_loaders import load_ed_note_admitted

    out = [
        _Term(term, (entry.vital,), "all", frozenset(entry.states))
        for entry in load_ed_note_admitted().exam_vital_terms
        for term in entry.terms.get(code) or entry.terms["en"]
    ]
    out += [
        _Term(term, tuple(extra.vitals), extra.agree, frozenset(extra.states))
        for extra in progress_exam_rules().extra_terms
        for term in extra.terms.get(code) or extra.terms["en"]
    ]
    return tuple(sorted(out, key=lambda term: -len(term.text)))


def child_low_bound(child: Any, edge: str) -> float:
    """The value below which a child's reading is "low": the band's normal-range
    ``low``, or for ``critical_low`` the first value above it (the YAML flags a
    value at or below ``critical_low``, so a reading is low when strictly
    below ``critical_low + 1``). A band without a ``critical_low`` uses ``low``."""
    if edge == "critical_low" and child.critical_low is not None:
        return float(child.critical_low) + 1
    return float(child.low)


def _override_low(ctx: NarrativeContext, vital: str) -> float | None:
    """The patient-specific ``low`` limit of ``vital`` (``limit_overrides``),
    ``None`` when no override applies."""
    overrides = [o for o in progress_exam_rules().limit_overrides if o.vital == vital]
    if not overrides:
        return None
    from clinosim.modules.document.narrative.renderers._resolvers import _patient_condition_codes

    disease_id = str(getattr(getattr(ctx, "disease_protocol", None), "disease_id", "") or "")
    codes = _patient_condition_codes(ctx)
    for o in overrides:
        if disease_id in o.disease_ids or any(c.startswith(tuple(o.chronic_code_prefixes)) for c in codes):
            return o.low
    return None


def spo2_low_override(ctx: NarrativeContext) -> float | None:
    """The SpO2 floor of the patient's own target range (a COPD patient's 88 %)
    in place of the adult limit, ``None`` for a patient without one."""
    return _override_low(ctx, "spo2")


def _limit(ctx: NarrativeContext, vital: str, limit: _Limit, when: Any) -> tuple[float | None, float | None, bool]:
    """``(low, high, high_inclusive)`` of ``vital`` for the patient: the
    age-banded pediatric range where it lists the vital, else the adult
    limit (a patient's own target range replacing the adult ``low``)."""
    months = age_in_completed_months(_o(getattr(ctx, "patient", None), "date_of_birth", None), when)
    child = pediatric_vital_range(vital, months)
    if child is not None:
        return child_low_bound(child, limit.child_low), child.high, False
    override = _override_low(ctx, vital)
    return (limit.low if override is None else override), limit.high, limit.high_inclusive


def period_states(ctx: NarrativeContext, readings: list) -> dict[str, set[str]]:
    """The state of each vital over the readings of a note's period:
    ``{vital: {"high"} | {"low"} | {"low", "high"} | {"normal"}}`` (a vital
    with no reading is left out), the pseudo-vital ``on_oxygen`` ("high" when
    the latest reading is on supplemental oxygen) and ``consciousness`` ("high" when
    an AVPU level other than Alert was recorded)."""
    rules = progress_exam_rules()
    when = getattr(ctx, "authored_datetime", None) or _o(getattr(ctx, "encounter", None), "admission_datetime", None)
    states: dict[str, set[str]] = {}
    for vital, limit in rules.limits.items():
        low, high, inclusive = _limit(ctx, vital, limit, when)
        values = [float(x) for x in (_o(r, vital, None) for r in readings) if x is not None]
        if not values:
            continue
        found: set[str] = set()
        if low is not None and min(values) < low:
            found.add("low")
        if high is not None and (max(values) >= high if inclusive else max(values) > high):
            found.add("high")
        states[vital] = found or {"normal"}
    if readings and _o(readings[-1], "on_supplemental_oxygen", False):
        states["on_oxygen"] = {"high"}
    levels = {str(_o(r, "consciousness_level", "") or "") for r in readings}
    if levels & {"V", "P", "U"}:
        states["consciousness"] = {"high"}
    return states


def current_states(ctx: NarrativeContext, readings: list) -> dict[str, set[str]]:
    """The state of each vital at the note's time: that of the latest recorded
    value of each vital among ``readings`` (the values the Objective prints),
    not of the period's extreme. A statement about how the patient is now
    ("tachypnea", "SpO2 low", "worsening") is judged on these; the extreme is
    stated only as a time-qualified peak (Issue #3401)."""
    from clinosim.modules.document.narrative._vitals_line import latest_vitals_set

    return period_states(ctx, [latest_vitals_set(readings)]) if readings else {}


def any_abnormal(states: dict[str, set[str]]) -> bool:
    """Whether a measured vital of the period (not the oxygen / pain
    pseudo-states) was low or high."""
    return any(
        s & {"low", "high"} for vital, s in states.items() if vital not in _PSEUDO_VITALS and vital != "pain_score"
    )


def _matches(text: str, code: str) -> list[_Term]:
    """The terms ``text`` states, the longest read first and consumed."""
    found: list[_Term] = []
    rest = text.lower()
    for term in _terms(code):
        if term.text.lower() in rest:
            rest = rest.replace(term.text.lower(), " ")
            found.append(term)
    return found


def _consistent(term: _Term, states: dict[str, set[str]]) -> bool:
    judged = [states[v] for v in term.vitals if v in states]
    if not judged:
        return True
    ok = [bool(s & term.states) for s in judged]
    return all(ok) if term.agree == "all" else any(ok)


def agreeing_clauses(text: str, states: dict[str, set[str]], lang: str) -> str:
    """``text`` without the clauses whose vital-sign statement the period's
    ``states`` contradict ("全身状態良好" on a febrile day)."""
    if not text or not states:
        return text
    code = normalize_lang(lang)
    rules = progress_exam_rules()
    separators = rules.clause_separators.get(code) or rules.clause_separators["en"]

    def keep(piece: str, level: int) -> str:
        if level == len(separators):
            return piece if all(_consistent(term, states) for term in _matches(piece, code)) else ""
        sep = separators[level]
        return sep.join(kept for kept in (keep(part, level + 1) for part in piece.split(sep)) if kept)

    return keep(text, 0)


def _states_stated(text: str, code: str) -> set[tuple[str, str]]:
    """The ``(vital, state)`` readings ``text`` states: by a single-vital
    term, or a term of illness (``agree: any``)."""
    stated: set[tuple[str, str]] = set()
    for term in _matches(text, code):
        if len(term.vitals) == 1 or term.agree == "any":
            stated |= {(v, s) for v in term.vitals for s in term.states}
    return stated


def progress_exam_findings(
    ctx: NarrativeContext, readings: list, phys_exam: dict[str, Any], severity: str, lang: str
) -> dict[str, str]:
    """The exam of a progress note per body system: the authored findings of
    the day without the clauses the period's readings contradict, plus each
    abnormal reading the system's text does not state. With no reading the
    authored text is returned as is."""
    from clinosim.modules.document.narrative.renderers._shared_helpers import (
        PHYSICAL_EXAM_SYSTEMS,
        select_exam_text,
    )

    states = period_states(ctx, readings)
    now = current_states(ctx, readings)
    code = normalize_lang(lang)
    findings: dict[str, str] = {}
    for system in PHYSICAL_EXAM_SYSTEMS:
        text = agreeing_clauses(select_exam_text(phys_exam.get(system), severity), states, lang)
        stated = _states_stated(text, code)
        sep = progress_exam_rules().clause_separators.get(code, ["", "", ""])[1] if text else ""
        added = [
            f.text.get(code) or f.text["en"]
            for f in progress_exam_rules().state_findings
            if f.system == system
            and f.state in now.get(f.vital, set())
            and (f.vital, f.state) not in stated
            and (f.text.get(code) or f.text["en"]) not in text
        ]
        if added:
            text = sep.join([text, *added]) if text else sep.join(added)
        if text:
            findings[system] = text
    return findings


def course_line(ctx: NarrativeContext, readings: list, previous: list, lang: str) -> str:
    """How the vital signs changed from the previous period (the Assessment's
    "improving / worsening / persisting"): the abnormal states at the end of the period
    (fever, tachycardia, tachypnea, low SpO2, hypotension, reduced
    consciousness, oxygen therapy), judged on the latest reading of each
    period, against those at the end of the previous period (Issue #3401).
    ``""`` without readings in both periods or without any abnormal state in
    either."""
    if not readings or not previous:
        return ""
    code = normalize_lang(lang)
    items = progress_exam_rules().course_items

    def named(rows: list) -> list[str]:
        states = current_states(ctx, rows)
        return [i.name.get(code) or i.name["en"] for i in items if i.state in states.get(i.vital, set())]

    now, before = named(readings), named(previous)
    if not now and not before:
        return ""
    sep = t("list_sep.serial", lang)
    if len(now) < len(before):
        return t("progress.course_improving", lang, list=sep.join(n for n in before if n not in now))
    if len(now) > len(before):
        return t("progress.course_worsening", lang, list=sep.join(n for n in now if n not in before))
    common = [n for n in now if n in before]
    return t("progress.course_persisting", lang, list=sep.join(common)) if common else ""


def worst_avpu(readings: list) -> str:
    """The worst AVPU level among ``readings`` (``""`` when none recorded)."""
    order = {"A": 0, "V": 1, "P": 2, "U": 3}
    levels = [str(_o(r, "consciousness_level", "") or "") for r in readings]
    levels = [lv for lv in levels if lv in order]
    return max(levels, key=order.__getitem__) if levels else ""


def unchanged_systems(findings: dict[str, str], previous: dict[str, str], consciousness_changed: bool) -> list[str]:
    """The body systems whose exam text is identical to the previous day's
    (Issue #3235), in exam order. The general system, which carries the
    consciousness clause, counts as changed when the day's worst AVPU
    changed. A system without text is never "unchanged"."""
    return [
        system
        for system, text in findings.items()
        if text and previous.get(system) == text and not (system == "general" and consciousness_changed)
    ]
