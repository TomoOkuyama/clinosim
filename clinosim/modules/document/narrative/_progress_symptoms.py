"""The respiratory symptom a daily progress note's Subjective states (Issue
#3454): how breathing is going, from the respiratory rate, SpO2 and oxygen
therapy of the latest reading of the note's period against the previous
period's, for the diseases of ``progress_symptoms.yaml``. The CIF holds no
cough, wheeze or sputum, so none is stated.
Data: ``reference_data/progress_symptoms.yaml``."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from clinosim.datafiles import load_validated_yaml
from clinosim.locale.i18n import t
from clinosim.locale.localized import normalize_lang
from clinosim.modules._shared import get_attr_or_key as _o

if TYPE_CHECKING:
    from clinosim.types.document import NarrativeContext

__all__ = ["ProgressSymptomRules", "progress_symptom_rules", "respiratory_symptom_line"]

_YAML = Path(__file__).resolve().parents[1] / "reference_data" / "progress_symptoms.yaml"


class _RespiratoryGroup(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    diseases: list[str] = Field(min_length=1)
    dyspnea_terms: dict[str, list[str]]

    @model_validator(mode="after")
    def _valid(self) -> _RespiratoryGroup:
        if "en" not in self.dyspnea_terms or not self.dyspnea_terms["en"]:
            raise ValueError("progress_symptoms.yaml: dyspnea_terms need English terms")
        disease_dir = Path(__file__).resolve().parents[2] / "disease" / "reference_data"
        unknown = sorted(d for d in self.diseases if not (disease_dir / f"{d}.yaml").exists())
        if unknown:
            raise ValueError(f"progress_symptoms.yaml: unknown disease ids {unknown}")
        return self


class ProgressSymptomRules(BaseModel):
    """``progress_symptoms.yaml`` (Issue #3454)."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    respiratory: _RespiratoryGroup


@lru_cache(maxsize=1)
def progress_symptom_rules() -> ProgressSymptomRules:
    """The respiratory disease group (``progress_symptoms.yaml``)."""
    return ProgressSymptomRules.model_validate(load_validated_yaml(_YAML, ProgressSymptomRules))


def _min_change(vital: str) -> float:
    """The move of ``vital`` that is a change worth stating: the ``min_change``
    of its ``progress_exam.yaml`` course item."""
    from clinosim.modules.document.narrative._progress_exam import progress_exam_rules

    for item in progress_exam_rules().course_items:
        if item.vital == vital and item.min_change is not None:
            return item.min_change
    raise ValueError(f"progress_exam.yaml: no min_change for course item {vital!r}")


def _breathing_abnormal(states: dict[str, set[str]]) -> bool:
    return (
        "high" in states.get("respiratory_rate", set())
        or "low" in states.get("spo2", set())
        or "high" in states.get("on_oxygen", set())
    )


def _direction(prev: dict[str, Any], cur: dict[str, Any], prev_oxygen: bool, cur_oxygen: bool) -> int:
    """+1 improving, -1 worsening, 0 unchanged between the two periods'
    latest readings (respiratory rate, SpO2, oxygen therapy)."""
    score = 0
    for vital, sign in (("respiratory_rate", -1), ("spo2", 1)):
        a, b = _o(prev, vital, None), _o(cur, vital, None)
        if a is None or b is None or abs(float(b) - float(a)) < _min_change(vital):
            continue
        score += sign if float(b) > float(a) else -sign
    if prev_oxygen and not cur_oxygen:
        score += 1
    elif cur_oxygen and not prev_oxygen:
        score -= 1
    return (score > 0) - (score < 0)


def _detail(prev: dict[str, Any], cur: dict[str, Any], lang: str, *, with_prev: bool) -> str:
    bits: list[str] = []
    for vital, key in (("respiratory_rate", "rr"), ("spo2", "spo2")):
        now = _o(cur, vital, None)
        if now is None:
            continue
        before = _o(prev, vital, None) if with_prev else None
        now_text = f"{float(now):.0f}"
        before_text = None if before is None else f"{float(before):.0f}"
        value = now_text if before_text in (None, now_text) else f"{before_text} → {now_text}"
        bits.append(t(f"progress.resp_detail_{key}", lang, v=value))
    return t("progress.resp_detail", lang, list=t("list_sep.serial", lang).join(bits)) if bits else ""


def respiratory_symptom_line(ctx: NarrativeContext, today: list, prev: list) -> str:
    """How breathing is going since the previous period, or ``""`` for a
    disease outside the respiratory group or a period without a reading.
    Dyspnea is named only for a disease whose chief complaint is dyspnea."""
    from clinosim.modules.document.narrative._progress_exam import current_states
    from clinosim.modules.document.narrative._vitals_line import latest_vitals_set

    rules = progress_symptom_rules().respiratory
    disease_id = getattr(getattr(ctx, "disease_protocol", None), "disease_id", "") or ""
    if disease_id not in rules.diseases or not today:
        return ""
    lang = ctx.target_lang
    code = normalize_lang(lang)
    from clinosim.modules.document.narrative.renderers.section_builders.chief_complaint import (
        chief_complaint_texts,
    )

    complaint = " ".join(chief_complaint_texts(ctx)).lower()
    terms = rules.dyspnea_terms.get(code) or rules.dyspnea_terms["en"]
    family = "dyspnea" if any(term.lower() in complaint for term in terms) else "status"

    cur, before = latest_vitals_set(today), latest_vitals_set(prev) if prev else {}
    now_abnormal = _breathing_abnormal(current_states(ctx, today))
    prev_abnormal = bool(prev) and _breathing_abnormal(current_states(ctx, prev))
    detail = _detail(before, cur, lang, with_prev=bool(prev))
    if now_abnormal and prev_abnormal:
        move = _direction(
            before,
            cur,
            bool(_o(before, "on_supplemental_oxygen", False)),
            bool(_o(cur, "on_supplemental_oxygen", False)),
        )
        state = {1: "improving", -1: "worsening", 0: "persistent"}[move]
    elif now_abnormal:
        state = "new" if prev else "present"
    elif prev_abnormal:
        state = "resolved"
    else:
        return t("progress.resp_status_stable", lang, detail=detail)
    return t(f"progress.resp_{family}_{state}", lang, detail=detail)
