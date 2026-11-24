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
from clinosim.modules.document.narrative._vitals_line import latest_vitals_set
from clinosim.modules.observation.pediatric_ranges import age_in_completed_months, pediatric_vital_range
from clinosim.timeutil import parse_iso_datetime

if TYPE_CHECKING:
    from clinosim.types.document import NarrativeContext

__all__ = [
    "ProgressExamRules",
    "current_states",
    "spo2_low_override",
    "agreeing_clauses",
    "consciousness_assessment_line",
    "course_line",
    "period_states",
    "progress_exam_findings",
    "progress_exam_rules",
    "coma_avpu",
    "unchanged_systems",
    "worst_avpu",
]

_YAML = Path(__file__).resolve().parents[1] / "reference_data" / "progress_exam.yaml"
_State = Literal["low", "normal", "high"]
_PSEUDO_VITALS = ("on_oxygen", "consciousness")
_AVPU_ORDER = {"A": 0, "V": 1, "P": 2, "U": 3}


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
    # The move of the vital's latest value (its unit) that makes a persisting
    # state improving / worsening; ``None`` for a pseudo-vital.
    min_change: float | None = Field(default=None, gt=0)


class _Coma(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    work_up: Annotated[dict[str, list[str]], AfterValidator(_has_english)]
    # The neurological finding of each coma AVPU level; the keys are the levels.
    neurological: dict[str, _Localized] = Field(min_length=1)

    @model_validator(mode="after")
    def _levels(self) -> _Coma:
        if set(self.neurological) - {"P", "U"}:
            raise ValueError("progress_exam.yaml: coma levels must be P or U")
        return self


class _ConsciousnessCourse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    min_days: int = Field(ge=1)
    delirium_complications: list[str] = Field(min_length=1)
    work_up: Annotated[dict[str, list[str]], AfterValidator(_has_english)]
    coma: _Coma


class _CourseState(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    resolved_window_hours: float = Field(gt=0)
    resolved_min_readings: int = Field(ge=2)


class _SustainedLow(BaseModel):
    """A vital whose low reading counts only when sustained, for a patient up
    to ``max_age_months`` old (Issue #3563)."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    max_age_months: int = Field(ge=0)
    min_readings: int = Field(ge=2)
    accompanying_vitals: list[str] = Field(default_factory=list)


class ProgressExamRules(BaseModel):
    """``progress_exam.yaml`` (Issue #3235)."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    limits: dict[str, _Limit] = Field(min_length=1)
    limit_overrides: list[_LimitOverride] = Field(default_factory=list)
    sustained_low: dict[str, _SustainedLow] = Field(default_factory=dict)
    clause_separators: Annotated[dict[str, list[str]], AfterValidator(_has_english)]
    terminal_forms: dict[str, dict[str, str]] = Field(default_factory=dict)
    extra_terms: list[_ExtraTerm]
    state_findings: list[_StateFinding]
    course_items: list[_CourseItem]
    course_state: _CourseState
    consciousness_course: _ConsciousnessCourse

    @model_validator(mode="after")
    def _known_vitals_and_systems(self) -> ProgressExamRules:
        from clinosim.modules.document.narrative.renderers._shared_helpers import PHYSICAL_EXAM_SYSTEMS

        known = set(self.limits) | set(_PSEUDO_VITALS)
        named = {o.vital for o in self.limit_overrides} | set(self.sustained_low)
        named |= {v for rule in self.sustained_low.values() for v in rule.accompanying_vitals}
        named |= {v for term in self.extra_terms for v in term.vitals}
        named |= {f.vital for f in self.state_findings} | {c.vital for c in self.course_items}
        if named - known:
            raise ValueError(f"progress_exam.yaml: vitals without a limit {sorted(named - known)}")
        unmeasured = sorted(c.vital for c in self.course_items if c.vital in self.limits and c.min_change is None)
        if unmeasured:
            raise ValueError(f"progress_exam.yaml: course items of a measured vital need min_change {unmeasured}")
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


def _abnormal(ctx: NarrativeContext, reading: Any, vital: str, when: Any) -> bool:
    """Whether ``reading`` records ``vital`` outside its limits."""
    value = _o(reading, vital, None)
    limit = progress_exam_rules().limits.get(vital)
    if value is None or limit is None:
        return False
    low, high, inclusive = _limit(ctx, vital, limit, when)
    x = float(value)
    return (low is not None and x < low) or (high is not None and (x >= high if inclusive else x > high))


def _low_marks(ctx: NarrativeContext, vital: str, rows: list, when: Any) -> list[bool]:
    """Per row of ``rows`` (oldest first), whether its ``vital`` reading is a
    low that counts. A reading below the limit always counts, except for the
    ``sustained_low`` patients (newborns, Issue #3563), where it counts only
    inside a run of ``min_readings`` consecutive low readings of the vital or
    with another vital abnormal at the same reading."""
    rules = progress_exam_rules()
    limit = rules.limits[vital]
    low = _limit(ctx, vital, limit, when)[0]
    raw = [low is not None and _o(r, vital, None) is not None and float(_o(r, vital, None)) < low for r in rows]
    rule = rules.sustained_low.get(vital)
    months = age_in_completed_months(_o(getattr(ctx, "patient", None), "date_of_birth", None), when)
    if rule is None or months is None or months > rule.max_age_months:
        return raw
    measured = [i for i, r in enumerate(rows) if _o(r, vital, None) is not None]
    marks = [False] * len(rows)
    run: list[int] = []
    for i in [*measured, -1]:
        if i >= 0 and raw[i]:
            run.append(i)
            continue
        if len(run) >= rule.min_readings:
            for j in run:
                marks[j] = True
        run = []
    for i in measured:
        if raw[i] and any(_abnormal(ctx, rows[i], v, when) for v in rule.accompanying_vitals):
            marks[i] = True
    return marks


def period_states(
    ctx: NarrativeContext,
    readings: list,
    before: list | tuple = (),
    after: list | tuple = (),
    *,
    sustained: bool = True,
) -> dict[str, set[str]]:
    """The state of each vital over the readings of a note's period:
    ``{vital: {"high"} | {"low"} | {"low", "high"} | {"normal"}}`` (a vital
    with no reading is left out), the pseudo-vital ``on_oxygen`` ("high" when
    the latest reading is on supplemental oxygen) and ``consciousness`` ("high" when
    an AVPU level other than Alert was recorded). ``before`` / ``after`` are the
    neighbouring readings that only decide whether a low of ``readings`` is
    sustained (Issue #3563); ``sustained=False`` judges each reading alone."""
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
            chain = [*before, *readings, *after]
            marks = _low_marks(ctx, vital, chain, when)[len(before) : len(before) + len(readings)]
            if any(marks) or not sustained:
                found.add("low")
        if high is not None and (max(values) >= high if inclusive else max(values) > high):
            found.add("high")
        states[vital] = found or {"normal"}
    # The latest reading that measured oxygen (a temperature-only row did not, Issue #3644).
    measured_o2 = [r for r in readings if _o(r, "on_supplemental_oxygen", None) is not None]
    if measured_o2 and _o(measured_o2[-1], "on_supplemental_oxygen", False):
        states["on_oxygen"] = {"high"}
    levels = {str(_o(r, "consciousness_level", "") or "") for r in readings}
    if levels & {"V", "P", "U"}:
        states["consciousness"] = {"high"}
    return states


def current_states(ctx: NarrativeContext, readings: list, before: list | tuple = ()) -> dict[str, set[str]]:
    """The state of each vital at the note's time: that of the latest recorded
    value of each vital among ``readings`` (the values the Objective prints),
    not of the period's extreme. A statement about how the patient is now
    ("tachypnea", "SpO2 low", "worsening") is judged on these; the extreme is
    stated only as a time-qualified peak (Issue #3401). A newborn's low counts
    only when sustained over ``before`` + ``readings`` (Issue #3563)."""
    from clinosim.modules.document.narrative._vitals_line import latest_vitals_set

    if not readings:
        return {}
    states = period_states(ctx, [latest_vitals_set(readings)], sustained=False)
    when = getattr(ctx, "authored_datetime", None) or _o(getattr(ctx, "encounter", None), "admission_datetime", None)
    chain = [*before, *readings]
    for vital in progress_exam_rules().sustained_low:
        if "low" not in states.get(vital, set()):
            continue
        marks = _low_marks(ctx, vital, chain, when)
        last = max(i for i, r in enumerate(chain) if _o(r, vital, None) is not None)
        if not marks[last]:
            states[vital] = (states[vital] - {"low"}) or {"normal"}
    return states


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

    terminals = rules.terminal_forms.get(code, {})

    def keep(piece: str, level: int) -> str:
        if level == len(separators):
            return piece if all(_consistent(term, states) for term in _matches(piece, code)) else ""
        sep = separators[level]
        kept_parts = [kept for kept in (keep(part, level + 1) for part in piece.split(sep)) if kept]
        result = sep.join(kept_parts)
        # Issue #3456: a sentence that lost its trailing clause ends in the
        # connective form of its last verb ("脱水を認め"); finish it.
        if level == 1 and result and result != piece:
            for connective, final in terminals.items():
                if result.endswith(connective):
                    return result[: -len(connective)] + final
        return result

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
    ctx: NarrativeContext,
    readings: list,
    phys_exam: dict[str, Any],
    severity: str,
    lang: str,
    before: list | tuple = (),
) -> dict[str, str]:
    """The exam of a progress note per body system: the authored findings of
    the day without the clauses the period's readings contradict, plus each
    abnormal reading the system's text does not state. With no reading the
    authored text is returned as is."""
    from clinosim.modules.document.narrative.renderers._shared_helpers import (
        PHYSICAL_EXAM_SYSTEMS,
        select_exam_text,
    )

    states = period_states(ctx, readings, before)
    now = current_states(ctx, readings, before)
    code = normalize_lang(lang)
    coma = progress_exam_rules().consciousness_course.coma
    coma_level = coma_avpu(readings)
    sep_coma = progress_exam_rules().clause_separators.get(code, ["", "", ""])[1]
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
        if system == "neurological" and coma_level:
            coma_text = coma.neurological[coma_level]
            coma_text = coma_text.get(code) or coma_text["en"]
            text = sep_coma.join([text, coma_text]) if text else coma_text
        if text:
            findings[system] = text
    return findings


def course_line(ctx: NarrativeContext, readings: list, previous: list, lang: str) -> str:
    """How the vital signs changed from the previous period (the Assessment's
    "improving / worsening / persisting"): the abnormal states at the end of the period
    (fever, tachycardia, tachypnea, low SpO2, hypotension, reduced
    consciousness, oxygen therapy), judged on the latest reading of each
    period, against those at the end of the previous period (Issue #3401).
    ``""`` without readings in both periods or without any finding to state.
    Each finding is stated in the one state :func:`finding_states` gives it
    (Issue #3541), so the line and the Subjective never disagree."""
    if not readings or not previous:
        return ""
    from clinosim.modules.document.narrative._progress_state import finding_states

    code = normalize_lang(lang)
    items = progress_exam_rules().course_items
    states = finding_states(ctx, readings, previous)
    sep = t("list_sep.serial", lang)
    resolved: list[str] = []
    easing: list[str] = []
    new: list[str] = []
    # Issue #3455: a state present in both periods is persisting unless the
    # vital's latest value moved by its ``min_change`` between them.
    cur, prev = latest_vitals_set(readings), latest_vitals_set(previous)
    persisting: list[str] = []
    improving: list[str] = []
    worsening: list[str] = []
    for i in items:
        label = i.name.get(code) or i.name["en"]
        state = states.get((i.vital, i.state), "unknown")
        if state == "resolved":
            resolved.append(label)
        elif state == "improving":
            easing.append(label)
        elif state == "new":
            new.append(label)
        elif state == "persisting":
            a, b = _o(prev, i.vital, None), _o(cur, i.vital, None)
            if i.min_change is None or a is None or b is None or abs(float(b) - float(a)) < i.min_change:
                persisting.append(label)
                continue
            moved_down = float(b) < float(a)
            detail = f"{label} {_fmt(float(a), i.min_change)} → {_fmt(float(b), i.min_change)}"
            (improving if moved_down == (i.state == "high") else worsening).append(detail)
    lines = []
    for key, group in (
        ("progress.course_improving", resolved),
        ("progress.course_easing", easing),
        ("progress.course_worsening", new),
        ("progress.course_persisting", persisting),
        ("progress.course_persisting_improving", improving),
        ("progress.course_persisting_worsening", worsening),
    ):
        if group:
            lines.append(t(key, lang, list=sep.join(group)))
    return t("list_sep.sentence_gap", lang).join(lines)


def consciousness_assessment_line(daily: list[list], complications: list[str], lang: str) -> str:
    """The Assessment's statement of a level of consciousness that stays below
    Alert (Issue #3471): ``daily`` is the readings of each hospital day up to
    the note, the note's own day first. A day counts when the latest AVPU of
    its readings is below Alert; the line is written from
    ``consciousness_course.min_days`` consecutive such days. It names the
    problem and its cause work-up with delirium as one differential, and
    names delirium itself only when ``complications`` (the stay's complication
    tokens known at the note) record one. ``""`` otherwise."""
    rules = progress_exam_rules().consciousness_course
    levels: list[str] = []
    for readings in daily:
        latest = ""
        for r in reversed(readings):
            level = str(_o(r, "consciousness_level", "") or "")
            if level in _AVPU_ORDER:
                latest = level
                break
        if latest in ("", "A"):
            break
        levels.append(latest)
    if len(levels) < rules.min_days:
        return ""
    code = normalize_lang(lang)
    if levels[0] in rules.coma.neurological:
        coma_causes = t("list_sep.serial", lang).join(rules.coma.work_up.get(code) or rules.coma.work_up["en"])
        return t("progress.consciousness_coma_workup", lang, a=levels[0], n=len(levels), causes=coma_causes)
    causes = t("list_sep.serial", lang).join(rules.work_up.get(code) or rules.work_up["en"])
    recorded = [c for c in complications if "_".join(c.strip().lower().split()) in rules.delirium_complications]
    if recorded:
        from clinosim.modules.document.narrative._localization import _localize_complication

        return t(
            "progress.consciousness_delirium_workup",
            lang,
            a=levels[0],
            n=len(levels),
            name=_localize_complication(recorded[0], lang),
            causes=causes,
        )
    return t("progress.consciousness_differential_workup", lang, a=levels[0], n=len(levels), causes=causes)


def delirium_active(ctx: NarrativeContext) -> bool:
    """Whether a delirium complication of the stay is active on the note's
    hospital day (Issue #3678): its onset is at or before the day (and before
    the authored time, when both are known) and its recorded resolution day,
    if any, is after the day. A delirium without a recorded course lasts to
    the end of the stay."""
    names = set(progress_exam_rules().consciousness_course.delirium_complications)
    as_of = getattr(ctx, "authored_datetime", None)
    for event in getattr(ctx, "complications_events", None) or []:
        if "_".join(str(_o(event, "name", "") or "").strip().lower().split()) not in names:
            continue
        onset_day = _o(event, "onset_day", None)
        if onset_day is None or int(onset_day) > ctx.day_index:
            continue
        onset_at = parse_iso_datetime(_o(event, "onset_datetime", None), lenient=True)
        if as_of is not None and onset_at is not None and onset_at > as_of:
            continue
        resolved = _o(event, "resolution_day", None)
        if resolved is not None and int(resolved) <= ctx.day_index:
            continue
        return True
    return False


def _fmt(value: float, step: float) -> str:
    """A vital value with the decimals its meaningful change needs."""
    return f"{value:.1f}" if step < 1 else f"{value:.0f}"


def worst_avpu(readings: list) -> str:
    """The worst AVPU level among ``readings`` (``""`` when none recorded)."""
    order = {"A": 0, "V": 1, "P": 2, "U": 3}
    levels = [str(_o(r, "consciousness_level", "") or "") for r in readings]
    levels = [lv for lv in levels if lv in order]
    return max(levels, key=order.__getitem__) if levels else ""


def coma_avpu(readings: list) -> str:
    """The worst AVPU level of ``readings`` when it is a coma level (Pain or
    Unresponsive, Issue #3544), else ``""``."""
    worst = worst_avpu(readings)
    return worst if worst in progress_exam_rules().consciousness_course.coma.neurological else ""


def unchanged_systems(
    findings: dict[str, str],
    previous: dict[str, str],
    consciousness_changed: bool,
    *,
    new_in_period: bool = False,
    coma: bool = False,
) -> list[str]:
    """The body systems whose exam text is identical to the previous day's
    (Issue #3235), in exam order. The general system, which carries the
    consciousness clause, counts as changed when the day's worst AVPU
    changed. A system without text is never "unchanged". Nothing is
    "unchanged" when something new happened in the period (``new_in_period``,
    a complication since the previous note), and a comatose patient's
    neurological exam is always stated (Issue #3544)."""
    if new_in_period:
        return []
    return [
        system
        for system, text in findings.items()
        if text
        and previous.get(system) == text
        and not (system == "general" and consciousness_changed)
        and not (system == "neurological" and coma)
    ]
