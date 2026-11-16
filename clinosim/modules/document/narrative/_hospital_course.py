"""The sentences of a discharge summary's hospital course (Issue #3246).

Each function reads one part of the record and returns its sentence in the
note's language, with the ``ctx`` field it read, or ``("", "")`` when the
record has nothing for it (silence, never a filler):

- :func:`readmission_sentence` — the stay is a readmission (``is_readmission``);
  the previous stay is not described, because the record holds only its id;
- :func:`treatments_sentence` — the drugs given, grouped by the tiers of
  ``drug_plan_priority.yaml``;
- :func:`procedures_sentence` — the procedures with the date each was first done;
- :func:`complications_sentence` — the in-hospital complications with the
  hospital day of onset;
- :func:`notable_labs_sentence` — panic results and results naming an
  abnormality (``lab_timeseries.select_notable_labs`` day by day), with the
  drugs given for them;
- :func:`medication_changes_sentence` — home medications at admission
  against the discharge prescription;
- :func:`discharge_condition_sentence` — disposition and the Barthel Index in
  force at discharge.

The limits and the abnormality-treatment table are in
``reference_data/hospital_course.yaml``. Hospital day N is the calendar day
N-1 after admission (the admission day is hospital day 1).
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from clinosim.datafiles import load_validated_yaml
from clinosim.locale.i18n import t
from clinosim.modules._shared import get_attr_or_key as _o
from clinosim.timeutil import parse_iso_datetime

if TYPE_CHECKING:
    from clinosim.types.document import NarrativeContext

__all__ = [
    "HospitalCourseRules",
    "complications_sentence",
    "discharge_condition_sentence",
    "hospital_course_rules",
    "medication_changes_sentence",
    "notable_labs_sentence",
    "procedures_sentence",
    "readmission_sentence",
    "treatments_sentence",
]

_RULES_YAML = Path(__file__).resolve().parents[1] / "reference_data" / "hospital_course.yaml"

# Strength of a dose instruction ("25mg", "81mg PO daily", "8.4 g").
_STRENGTH = re.compile(r"(\d+(?:\.\d+)?)\s*(mg|mcg|μg|g|units?|IU|mL)\b", re.IGNORECASE)


class _Response(BaseModel):
    model_config = ConfigDict(extra="forbid")
    drugs: list[str] = Field(default_factory=list)
    classes: list[str] = Field(default_factory=list)


class _Sides(BaseModel):
    model_config = ConfigDict(extra="forbid")
    high: _Response | None = None
    low: _Response | None = None


class _Treatments(BaseModel):
    model_config = ConfigDict(extra="forbid")
    max_named_per_tier: int = Field(gt=0)
    excluded_classes: list[str] = Field(default_factory=list)
    excluded_drugs: list[str] = Field(default_factory=list)


class _NotableLabs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    max_listed: int = Field(gt=0)
    response_window_hours: float = Field(gt=0)
    responses: dict[str, _Sides] = Field(default_factory=dict)


class _MedicationChanges(BaseModel):
    model_config = ConfigDict(extra="forbid")
    max_listed: int = Field(gt=0)


class HospitalCourseRules(BaseModel):
    """``hospital_course.yaml`` (Issue #3246)."""

    model_config = ConfigDict(extra="forbid")
    treatments: _Treatments
    notable_labs: _NotableLabs
    medication_changes: _MedicationChanges

    @model_validator(mode="after")
    def _known_drugs(self) -> HospitalCourseRules:
        from clinosim.codes.drugs import all_drug_ids, drug_classes

        ids = set(all_drug_ids())
        known = {c for d in ids for c in drug_classes(d)}
        responses = [r for s in self.notable_labs.responses.values() for r in (s.high, s.low) if r is not None]
        bad = sorted(c for c in self.treatments.excluded_classes if c not in known)
        bad += sorted(c for r in responses for c in r.classes if c not in known)
        bad += sorted(d for r in responses for d in r.drugs if d not in ids)
        bad += sorted(d for d in self.treatments.excluded_drugs if d not in ids)
        if bad:
            raise ValueError(f"hospital_course.yaml: unknown drug ids or classes {bad}")
        return self


@lru_cache(maxsize=1)
def hospital_course_rules() -> HospitalCourseRules:
    """The limits and abnormality treatments of the hospital course."""
    return HospitalCourseRules.model_validate(load_validated_yaml(_RULES_YAML, HospitalCourseRules))


def _admission(ctx: NarrativeContext) -> datetime | None:
    enc = getattr(ctx, "encounter", None)
    raw = _o(enc, "admission_datetime", None) if enc is not None else None
    return parse_iso_datetime(raw, lenient=True) if raw is not None else None


def _capped(names: list[str], cap: int, lang: str) -> str:
    text = t("list_sep.serial", lang).join(names[:cap])
    if len(names) > cap:
        text += t("current_medications.truncate_suffix", lang, n=len(names) - cap)
    return text


def _known_at(ctx: NarrativeContext, when: datetime | None) -> bool:
    as_of = getattr(ctx, "authored_datetime", None)
    return as_of is None or when is None or when <= as_of


def _drug_ref(m: Any) -> str:
    from clinosim.codes.drugs import drug_key
    from clinosim.modules._shared import strip_protocol_prefix

    name, _ = strip_protocol_prefix(str(_o(m, "drug_name", "") or ""))
    return str(_o(m, "drug_id", "") or "") or drug_key(name)


def _drug_name(m: Any, lang: str) -> str:
    from clinosim.codes.drugs import drug_display
    from clinosim.locale.free_text import localize_drug_name
    from clinosim.modules._shared import strip_protocol_prefix

    ref = str(_o(m, "drug_id", "") or "")
    name, _ = strip_protocol_prefix(str(_o(m, "drug_name", "") or ""))
    return (drug_display(ref, lang) if ref else None) or drug_display(name, lang) or localize_drug_name(name, lang)


def _given(ctx: NarrativeContext) -> list[tuple[datetime | None, Any]]:
    """The MAR doses given (not held) by the time the summary is written, in
    time order (undated doses last, in record order)."""
    doses: list[tuple[int, datetime | None, Any]] = []
    for i, m in enumerate(ctx.medications or []):
        if str(_o(m, "status", "") or "given") != "given":
            continue
        raw = _o(m, "actual_datetime", None) or _o(m, "scheduled_datetime", None)
        when = parse_iso_datetime(raw, lenient=True) if raw is not None else None
        if _known_at(ctx, when):
            doses.append((i, when, m))
    doses.sort(key=lambda d: (d[1] is None, d[1] or datetime.min, d[0]))
    return [(when, m) for _, when, m in doses]


def readmission_sentence(ctx: NarrativeContext) -> tuple[str, str]:
    """That the stay is a readmission after a recent discharge, with its
    number; nothing about the previous stay (the record holds only its id)."""
    if not getattr(ctx, "is_readmission", False):
        return "", ""
    number = int(getattr(ctx, "readmission_number", 0) or 0)
    key = "hospital_course.readmission_numbered" if number > 0 else "hospital_course.readmission"
    return t(key, ctx.target_lang, n=number), "ctx.is_readmission"


def treatments_sentence(ctx: NarrativeContext) -> tuple[str, str]:
    """The drugs given during the stay by tier of ``drug_plan_priority.yaml``
    (vasoactive, antimicrobial, ...), first given first within a tier."""
    from clinosim.codes.drugs import drug_classes
    from clinosim.modules.document.narrative._medication_plan import drug_tier, medication_plan_rules

    lang = ctx.target_lang
    rules = hospital_course_rules().treatments
    tiers = medication_plan_rules().tiers
    excluded = set(rules.excluded_classes)
    by_tier: dict[int, list[str]] = {}
    seen: set[str] = set()
    for _, m in _given(ctx):
        ref = _drug_ref(m)
        if not ref or ref in seen:
            continue
        seen.add(ref)
        if ref in rules.excluded_drugs or excluded & set(drug_classes(ref)):
            continue
        tier = drug_tier(ref, str(_o(m, "route", "") or ""))
        if tier >= len(tiers):
            continue
        name = _drug_name(m, lang)
        if name and name not in by_tier.setdefault(tier, []):
            by_tier[tier].append(name)
    if not by_tier:
        return "", ""
    groups = [
        t(
            "hospital_course.treatment_group",
            lang,
            label=t(f"hospital_course.treatment_tier.{tiers[i].name}", lang),
            list=_capped(names, rules.max_named_per_tier, lang),
        )
        for i, names in sorted(by_tier.items())
    ]
    return t("hospital_course.treatments_line", lang, list=t("hospital_course.group_sep", lang).join(groups)), (
        "ctx.medications"
    )


def procedures_sentence(ctx: NarrativeContext) -> tuple[str, str]:
    """The procedures of the stay, each with the date it was first done."""
    from clinosim.modules.document.narrative.renderers._shared_helpers import procedure_prose_name

    lang = ctx.target_lang
    first: dict[str, str] = {}
    for proc in ctx.procedures or []:
        start = parse_iso_datetime(_o(proc, "start_datetime", None), lenient=True)
        if not _known_at(ctx, start):
            continue
        name = procedure_prose_name(proc, lang)
        if name and name not in first:
            first[name] = start.date().isoformat() if start is not None else ""
    if not first:
        return "", ""
    items = [
        t("hospital_course.procedure_with_date", lang, name=name, date=date) if date else name
        for name, date in first.items()
    ]
    return t("hospital_course.procedures_line", lang, list=t("list_sep.serial", lang).join(items)), "ctx.procedures"


def complications_sentence(ctx: NarrativeContext) -> tuple[str, str]:
    """The in-hospital complications with the hospital day of onset (the
    event's own onset, else that of the working diagnosis of the same id)."""
    from clinosim.modules.document.narrative._localization import _localize_complication

    lang = ctx.target_lang
    wd_onset = {
        str(_o(wd, "disease_id", "")): _o(wd, "onset_day", None) for wd in (getattr(ctx, "working_diagnoses", []) or [])
    }
    phrases: list[str] = []
    seen: set[str] = set()
    for event in getattr(ctx, "complications_events", []) or []:
        name = str(_o(event, "name", "") or "")
        if not name or name in seen:
            continue
        seen.add(name)
        onset = parse_iso_datetime(_o(event, "onset_datetime", None), lenient=True)
        if not _known_at(ctx, onset):
            continue
        day = _o(event, "onset_day", None)
        if day is None:
            day = wd_onset.get(name)
        label = _localize_complication(name, lang)
        phrases.append(
            t("hospital_course.complication_with_onset", lang, day=int(day) + 1, label=label)
            if isinstance(day, int)
            else label
        )
    if not phrases:
        return "", ""
    return t("hospital_course.complications_line", lang, list=t("list_sep.serial", lang).join(phrases)), (
        "ctx.complications_events"
    )


def _response_drugs(ctx: NarrativeContext, lab: Any, side: str | None) -> list[str]:
    """The drugs of the abnormality's response list given within the response
    window after ``lab`` (``hospital_course.yaml``), first given first."""
    from clinosim.codes.drugs import drug_classes
    from clinosim.modules.document.narrative.lab_timeseries import _lab_name
    from clinosim.modules.observation.engine import canonical_lab_name

    rules = hospital_course_rules().notable_labs
    sides = rules.responses.get(canonical_lab_name(_lab_name(lab)))
    response = getattr(sides, side) if sides is not None and side in ("high", "low") else None
    at = parse_iso_datetime(_o(lab, "result_datetime", None), lenient=True)
    if response is None or at is None:
        return []
    until = at + timedelta(hours=rules.response_window_hours)
    names: list[str] = []
    for when, m in _given(ctx):
        if when is None or not at <= when <= until:
            continue
        ref = _drug_ref(m)
        if ref in response.drugs or set(drug_classes(ref)) & set(response.classes):
            name = _drug_name(m, ctx.target_lang)
            if name and name not in names:
                names.append(name)
    return names


def notable_labs_sentence(ctx: NarrativeContext) -> tuple[str, str]:
    """The stay's panic results and results naming an abnormality, one per
    analyte and abnormality at its most extreme value, with its hospital day
    and the drugs given for it."""
    from clinosim.modules.document.narrative._notable_labs import notable_lab_entry
    from clinosim.modules.document.narrative.lab_timeseries import (
        _PANIC_FLAGS,
        _lab_day,
        _lab_name,
        _numeric,
        flag_side,
        select_notable_labs,
    )
    from clinosim.modules.observation.engine import canonical_lab_name

    lang = ctx.target_lang
    admitted = _admission(ctx)
    labs = [
        lab
        for lab in ctx.lab_results or []
        if _known_at(ctx, parse_iso_datetime(_o(lab, "result_datetime", None), lenient=True))
    ]
    days = sorted({d for d in (_lab_day(lab, admitted) for lab in labs) if d is not None})
    picked: dict[tuple[str, str], tuple[int, Any]] = {}
    for day in days:
        for item in select_notable_labs(labs, admitted, day):
            flag = str(_o(item.lab, "flag", "") or "")
            if flag not in _PANIC_FLAGS and item.finding is None:
                continue
            side = flag_side(item.lab) or ""
            key = (canonical_lab_name(_lab_name(item.lab)), item.finding or side)
            value = _numeric(_o(item.lab, "value", None))
            current = picked.get(key)
            if current is not None:
                old = _numeric(_o(current[1].lab, "value", None))
                worse = value is not None and old is not None and (value < old if side == "low" else value > old)
                if not worse:
                    continue
            picked[key] = (day, item)
    if not picked:
        return "", ""
    rules = hospital_course_rules().notable_labs
    items: list[str] = []
    for day, item in sorted(picked.values(), key=lambda p: p[0])[: rules.max_listed]:
        text = t("hospital_course.lab_on_day", lang, entry=notable_lab_entry(item, lang), day=day + 1)
        drugs = _response_drugs(ctx, item.lab, flag_side(item.lab))
        if drugs:
            text = t("hospital_course.lab_treated", lang, item=text, list=t("list_sep.serial", lang).join(drugs))
        items.append(text)
    rest = len(picked) - rules.max_listed
    if rest > 0:
        items.append(t("progress.notable_labs_more", lang, count=rest))
    return t("hospital_course.labs_line", lang, list=t("hospital_course.group_sep", lang).join(items)), (
        "ctx.lab_results"
    )


def _strength(med: Any) -> str:
    match = _STRENGTH.search(str(_o(med, "dose", "") or ""))
    return f"{match.group(1)}{match.group(2)}" if match else ""


def medication_changes_sentence(ctx: NarrativeContext) -> tuple[str, str]:
    """The home medications at admission against the discharge prescription:
    drugs started, stopped and with a changed strength. Written only when
    the record has both the admission snapshot and a discharge prescription
    (else a change cannot be told from a missing list)."""
    from clinosim.codes.drugs import drug_key
    from clinosim.locale.free_text import localize_drug_name
    from clinosim.modules._shared import strip_protocol_prefix
    from clinosim.modules.document.narrative._template_helpers import _render_home_med_name

    lang = ctx.target_lang
    home = getattr(ctx, "home_medications_at_admission", None)
    discharge = list(getattr(ctx, "discharge_medications", None) or [])
    if home is None or not discharge:
        return "", ""

    def key(m: Any) -> str:
        name, _ = strip_protocol_prefix(str(_o(m, "drug_name", "") or ""))
        return str(_o(m, "drug_id", "") or "") or drug_key(name)

    before = {key(m): m for m in home if key(m)}
    after = {key(m): m for m in discharge if key(m)}
    started = [
        localize_drug_name(strip_protocol_prefix(str(_o(m, "drug_name", "") or ""))[0], lang)
        for k, m in after.items()
        if k not in before
    ]
    stopped = [_render_home_med_name(m, lang=lang) for k, m in before.items() if k not in after]
    changed: list[str] = []
    for k, m in before.items():
        if k not in after:
            continue
        old, new = _strength(m), _strength(after[k])
        if old and new and old.casefold() != new.casefold():
            changed.append(
                t("hospital_course.med_dose_item", lang, name=_render_home_med_name(m, lang=lang), old=old, new=new)
            )
    cap = hospital_course_rules().medication_changes.max_listed
    groups = [
        t(phrase, lang, list=_capped([n for n in names if n], cap, lang))
        for phrase, names in (
            ("hospital_course.med_started", started),
            ("hospital_course.med_stopped", stopped),
            ("hospital_course.med_dose_changed", changed),
        )
        if any(names)
    ]
    if not groups:
        return t("hospital_course.med_unchanged", lang), "ctx.discharge_medications"
    line = t("hospital_course.med_changes_line", lang, list=t("hospital_course.group_sep", lang).join(groups))
    return line, "ctx.discharge_medications"


def discharge_condition_sentence(ctx: NarrativeContext) -> tuple[str, str]:
    """Where the patient went and the Barthel Index in force at discharge."""
    from clinosim.locale.loader import narrative_label
    from clinosim.modules.document.narrative._as_of import in_force_at

    lang = ctx.target_lang
    enc = getattr(ctx, "encounter", None)
    disposition = str(_o(enc, "discharge_disposition", "") or "") if enc is not None else ""
    parts: list[str] = []
    if disposition:
        label = narrative_label("discharge_disposition", disposition, lang, fallback="")
        if label and label != disposition:
            parts.append(label)
    adl = in_force_at(list(getattr(ctx, "adl_assessments", None) or []), getattr(ctx, "authored_datetime", None))
    barthel = _o(adl, "barthel_score", None) if adl is not None else None
    if barthel is not None:
        parts.append(t("hospital_course.barthel", lang, score=barthel))
    if not parts:
        return "", ""
    line = t("hospital_course.discharge_condition_line", lang, list=t("list_sep.serial", lang).join(parts))
    return line, "ctx.encounter.discharge_disposition"
