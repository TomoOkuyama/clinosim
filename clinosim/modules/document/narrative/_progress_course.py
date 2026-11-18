"""What a daily progress note says about the hospital course beyond the vital
signs and the drug list (Issues #3235, #3247): the day after an operation or
procedure, how the key labs of the admission problem moved, and the Plan items
beyond medications (diet, rehabilitation, discharge arrangement).
Data: ``reference_data/progress_course.yaml``."""

from __future__ import annotations

from datetime import timedelta
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field

from clinosim.codes.snomed_concepts import SURGICAL_PROCEDURE
from clinosim.datafiles import load_validated_yaml
from clinosim.locale.i18n import t
from clinosim.modules._shared import get_attr_or_key as _o
from clinosim.timeutil import parse_iso_datetime

if TYPE_CHECKING:
    from clinosim.types.document import NarrativeContext

__all__ = [
    "ProgressCourseRules",
    "diet_line",
    "discharge_planning_line",
    "lab_course_lines",
    "post_procedure_line",
    "progress_course_rules",
    "rehab_line",
]

_YAML = Path(__file__).resolve().parents[1] / "reference_data" / "progress_course.yaml"


class _LabCourse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    max_listed: int = Field(gt=0)


class _DischargePlanning(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    days_before_discharge: int = Field(ge=0)
    groups: dict[str, str]


class ProgressCourseRules(BaseModel):
    """``progress_course.yaml`` (Issues #3235, #3247)."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    post_procedure_types: list[str]
    lab_course: _LabCourse
    discharge_planning: _DischargePlanning


@lru_cache(maxsize=1)
def progress_course_rules() -> ProgressCourseRules:
    """The post-procedure types, key-lab limit and discharge-planning window
    (``progress_course.yaml``)."""
    return ProgressCourseRules.model_validate(load_validated_yaml(_YAML, ProgressCourseRules))


def _note_day(ctx: NarrativeContext, as_of: Any) -> Any:
    if as_of is not None:
        return as_of.date()
    admitted = parse_iso_datetime(_o(getattr(ctx, "encounter", None), "admission_datetime", None), lenient=True)
    return admitted.date() + timedelta(days=ctx.day_index) if admitted else None


def post_procedure_line(ctx: NarrativeContext, as_of: Any) -> str:
    """ "Post-operative day N (operation)" for the latest operation of the stay
    started by the note's time, "post-procedure day N" for a catheter or other
    non-operative procedure of ``post_procedure_types``, and the "day of"
    form on its day; ``""`` without one."""
    from clinosim.modules.document.narrative.renderers._shared_helpers import procedure_names

    lang = ctx.target_lang
    enc_id = _o(getattr(ctx, "encounter", None), "encounter_id", "") or ""
    note_day = _note_day(ctx, as_of)
    if note_day is None:
        return ""
    non_operative = set(progress_course_rules().post_procedure_types)
    done = []
    for proc in getattr(ctx, "procedures", None) or []:
        ptype = str(_o(proc, "procedure_type", "") or "")
        if _o(proc, "encounter_id", "") != enc_id:
            continue
        if str(_o(proc, "category_code", "") or "") != SURGICAL_PROCEDURE and ptype not in non_operative:
            continue
        start = parse_iso_datetime(_o(proc, "start_datetime", None), lenient=True)
        if start is not None and start.date() <= note_day and (as_of is None or start <= as_of):
            done.append((start, proc, ptype in non_operative))
    if not done:
        return ""
    start, proc, procedure_only = max(done, key=lambda item: item[0])
    names = procedure_names([proc], lang)
    if not names:
        return ""
    days = (note_day - start.date()).days
    kind = "procedure" if procedure_only else "op"
    if days == 0:
        return t(f"progress.{kind}_day", lang, proc=names[0])
    return t(f"progress.post_{kind}_day", lang, n=days, proc=names[0])


def lab_course_lines(ctx: NarrativeContext, as_of: Any) -> list[str]:
    """Statements on how the key labs of the admission problem moved against
    their previous result: "improving (CRP 2.77 → 0.38 mg/dL)" and
    "worsening (...)". Only labs known at ``as_of`` and measured on the note's
    day count; none when the disease lists no admission labs."""
    from clinosim.codes.ucum import ucum_prose
    from clinosim.locale.loader import lab_display
    from clinosim.modules.document.narrative.lab_timeseries import lab_trend
    from clinosim.modules.observation.engine import format_lab_value

    lang = ctx.target_lang
    spec = getattr(getattr(ctx, "disease_protocol", None), "expected_lab_distributions", None)
    key_labs = set((_o(spec, "admission", None) or {}) if spec else ())
    if not key_labs:
        return []
    labs = list(getattr(ctx, "lab_results", None) or [])
    if as_of is not None:
        labs = [
            lab
            for lab in labs
            if (when := parse_iso_datetime(_o(lab, "result_datetime", None), lenient=True)) is not None
            and when <= as_of
        ]
    admission = _o(getattr(ctx, "encounter", None), "admission_datetime", None)
    units = {str(_o(lab, "lab_name", "") or ""): str(_o(lab, "unit", "") or "") for lab in labs}
    limit = progress_course_rules().lab_course.max_listed
    named: dict[str, list[str]] = {"improving": [], "worsening": []}
    for entry in lab_trend(labs, admission, ctx.day_index):
        direction = entry["direction"]
        name = str(entry["name"])
        if direction not in named or name not in key_labs or entry["prior_value"] is None:
            continue
        unit = units.get(name, "")
        unit_part = f" {ucum_prose(unit)}" if unit else ""
        before = format_lab_value(name, entry["prior_value"], unit)
        now = format_lab_value(name, entry["current_value"], unit)
        named[direction].append(f"{lab_display(name, lang)} {before} → {now}{unit_part}")
    sep = t("list_sep.serial", lang)
    return [
        t(f"progress.labs_course_{direction}", lang, list=sep.join(items[:limit]))
        for direction, items in named.items()
        if items
    ]


def diet_line(ctx: NarrativeContext, as_of: Any) -> str:
    """ "Diet: soft diet" — the stay's latest diet order known at the note's
    time ("Diet changed to ..." when it was placed since the previous note);
    ``""`` without a diet order."""
    from clinosim.locale.loader import resolve_localized_display
    from clinosim.locale.loaders.medical_display import load_diet_type_display
    from clinosim.modules.document.narrative._narrative_interpretation_thresholds import notable_lab_rules

    lang = ctx.target_lang
    admitted = parse_iso_datetime(_o(getattr(ctx, "encounter", None), "admission_datetime", None), lenient=True)
    window = timedelta(hours=notable_lab_rules().window_hours)
    latest = None
    for order in getattr(ctx, "orders", None) or []:
        if str(_o(order, "order_type", "") or "").lower().rsplit(".", 1)[-1] != "diet":
            continue
        placed = parse_iso_datetime(_o(order, "ordered_datetime", None), lenient=True)
        if placed is None or (as_of is not None and placed > as_of):
            continue
        if admitted is not None and as_of is None and (placed.date() - admitted.date()).days > ctx.day_index:
            continue
        if latest is None or placed >= latest[0]:
            latest = (placed, order)
    if latest is None:
        return ""
    placed, order = latest
    slug = str(_o(order, "display_name", "") or "")
    name = resolve_localized_display(load_diet_type_display().get(slug) or {}, lang, fallback="") or slug.replace(
        "_", " "
    )
    if as_of is not None:
        changed = placed > as_of - window
    elif admitted is not None:
        changed = (placed.date() - admitted.date()).days == ctx.day_index
    else:
        changed = False
    return t("progress.diet_changed" if changed and ctx.day_index > 0 else "progress.diet_continue", lang, diet=name)


def rehab_line(ctx: NarrativeContext, as_of: Any) -> str:
    """ "Rehabilitation continued (PT, OT)": the therapy types of the rehab
    sessions of the note's period (the window up to ``as_of``, else the
    hospital day); ``""`` without one."""
    from clinosim.modules.document.narrative._narrative_interpretation_thresholds import notable_lab_rules

    lang = ctx.target_lang
    admitted = parse_iso_datetime(_o(getattr(ctx, "encounter", None), "admission_datetime", None), lenient=True)
    window = timedelta(hours=notable_lab_rules().window_hours)
    kinds: list[str] = []
    for session in getattr(ctx, "rehab_sessions", None) or []:
        when = parse_iso_datetime(_o(session, "session_date", None), lenient=True)
        if when is None:
            continue
        if as_of is not None:
            inside = as_of - window < when <= as_of
        else:
            inside = admitted is not None and (when.date() - admitted.date()).days == ctx.day_index
        kind = str(_o(session, "therapy_type", "") or "")
        if inside and kind and kind not in kinds:
            kinds.append(kind)
    if not kinds:
        return ""
    return t("progress.rehab_continue", lang, types=t("list_sep.serial", lang).join(kinds))


def discharge_planning_line(ctx: NarrativeContext) -> str:
    """The discharge arrangement ("Discharge planning: home") on the last
    ``days_before_discharge`` + 1 days of a stay that ends in a discharge;
    ``""`` otherwise."""
    from clinosim.modules.document.narrative._narrative_utils import encounter_died

    rules = progress_course_rules().discharge_planning
    los = getattr(ctx, "los_days", 0) or 0
    enc = getattr(ctx, "encounter", None)
    if los <= 0 or ctx.day_index + 1 < los - rules.days_before_discharge or encounter_died(enc):
        return ""
    group = rules.groups.get(str(_o(enc, "discharge_disposition", "") or ""))
    return t(f"progress.discharge_planning.{group}", ctx.target_lang) if group else ""
