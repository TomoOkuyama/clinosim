"""The data-driven nursing items of a shift note (Issue #3478).

``reference_data/nursing_shift_items.yaml`` lists the items in order; each id
names a function below that reads the readings (and MAR) of the note's shift
window and returns ``(text, fact_tag)`` or ``None`` when the shift's record
does not show the item. Nothing is stated that the record of the shift does not
hold, and nothing recorded after the note's authored time (the window ends
there).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from clinosim.codes.snomed_concepts import SURGICAL_PROCEDURE
from clinosim.datafiles import load_validated_yaml
from clinosim.locale.i18n import t
from clinosim.modules._shared import get_attr_or_key as _o
from clinosim.modules.document.narrative._as_of import in_force_at
from clinosim.modules.document.narrative._delivery import delivery_mode
from clinosim.modules.document.narrative._drug_names import administered_drug_key, administered_drug_name
from clinosim.modules.document.narrative._narrative_interpretation_thresholds import progress_vitals_rules
from clinosim.modules.document.narrative._narrative_utils import is_neonate
from clinosim.modules.document.narrative._progress_course import diet_display, diet_order_at
from clinosim.modules.document.narrative._progress_exam import _limit, progress_exam_rules
from clinosim.modules.document.narrative._vitals_line import VENTILATOR_DEVICE, oxygen_text
from clinosim.modules.observation.nursing import news2_urgent_response_threshold
from clinosim.timeutil import parse_iso_datetime
from clinosim.types.document import NarrativeContext

__all__ = ["ITEM_FUNCTIONS", "ShiftData", "nursing_shift_item_lines", "nursing_shift_items_config"]

_YAML = Path(__file__).resolve().parents[1] / "reference_data" / "nursing_shift_items.yaml"
_AVPU_ORDER = {"A": 0, "V": 1, "P": 2, "U": 3}


class NursingShiftItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str
    source: str
    rule: str
    fact: str
    skip_neonate: bool
    only_neonate: bool = False
    only_postpartum: bool = False


class HoldReasonPattern(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    pattern: str
    phrase: str

    @model_validator(mode="after")
    def _compiles(self) -> HoldReasonPattern:
        re.compile(self.pattern)
        return self


class DeviceKind(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: str
    device_types: list[str]
    procedure_types: list[str]
    order_patterns: list[str]

    @model_validator(mode="after")
    def _compiles(self) -> DeviceKind:
        for p in self.order_patterns:
            re.compile(p)
        return self


class SiteObservation(BaseModel):
    """How long, and with which wording, the site of a procedure is observed."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: str
    max_days: int = Field(ge=0)


_SITE_KINDS = ("wound", "access_site", "pocket")


class NursingShiftItems(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[NursingShiftItem] = Field(min_length=1)
    device_kinds: list[DeviceKind] = Field(min_length=1)
    oral_routes: list[str] = Field(min_length=1)
    hold_reason_patterns: list[HoldReasonPattern]
    antipyretic_drug_keys: list[str] = Field(min_length=1)
    barthel_bands: list[tuple[int, str]] = Field(min_length=1)
    braden_bands: list[tuple[int, str]] = Field(min_length=1)
    braden_report_at_or_below: int
    braden_prevention_at_or_below: int
    adl_levels: dict[str, dict[int, str]]
    site_observation: dict[str, SiteObservation]

    @model_validator(mode="after")
    def _site_observation_valid(self) -> NursingShiftItems:
        if "surgical_wound" not in self.site_observation:
            raise ValueError("nursing_shift_items.yaml: site_observation needs the surgical_wound default")
        for cat, so in self.site_observation.items():
            if so.kind not in _SITE_KINDS:
                raise ValueError(
                    f"nursing_shift_items.yaml: site_observation.{cat}.kind {so.kind!r} not in {_SITE_KINDS}"
                )
        return self

    @model_validator(mode="after")
    def _unique_ids(self) -> NursingShiftItems:
        ids = [i.id for i in self.items]
        if len(set(ids)) != len(ids):
            raise ValueError("nursing_shift_items.yaml: duplicate item ids")
        return self


@lru_cache(maxsize=1)
def nursing_shift_items_config() -> NursingShiftItems:
    """The ordered nursing items and the antipyretic drugs (``nursing_shift_items.yaml``)."""
    return NursingShiftItems.model_validate(load_validated_yaml(_YAML, NursingShiftItems))


@dataclass
class ShiftData:
    """What an item reads: the shift window's readings (oldest first), the
    latest reading before the window, the window, and the shift's MAR."""

    ctx: NarrativeContext
    lang: str
    readings: list[Any]
    prior: Any | None
    window: tuple[datetime, datetime] | None
    doses: list[tuple[datetime, str, str]] = field(default_factory=list)  # (time, drug_key, localized name)
    not_given: list[Any] = field(default_factory=list)  # MAR rows of the shift held / refused / not available


def _avpu_of(v: Any) -> str:
    level = str(_o(v, "consciousness_level", "") or "")
    return level if level in _AVPU_ORDER else ""


def _cannot_self_report(level: str) -> bool:
    """True when ``level`` is a charted AVPU level at which the patient cannot
    give a report of their own or act for themselves: any level outside the
    progress note's ``self_report_avpu`` (``progress_vitals.yaml``, one gate for
    both notes). A blank level is not a finding (Issue #3536)."""
    return bool(level) and level not in progress_vitals_rules().self_report_avpu


def _impaired(d: ShiftData) -> bool:
    """The shift's latest charted consciousness (else the latest before the
    window) is below the self-report gate."""
    for v in reversed(d.readings):
        if _avpu_of(v):
            return _cannot_self_report(_avpu_of(v))
    return d.prior is not None and _cannot_self_report(_avpu_of(d.prior))


def _impaired_at(d: ShiftData, when: datetime) -> bool:
    """The same at a time: the latest charted level at or before ``when``."""
    level = ""
    for v in d.readings:
        w = _when(v)
        if w is not None and w <= when and _avpu_of(v):
            level = _avpu_of(v)
    if not level and d.prior is not None:
        level = _avpu_of(d.prior)
    return _cannot_self_report(level)


def _when(v: Any) -> datetime | None:
    return parse_iso_datetime(_o(v, "timestamp", None), lenient=True)


def _hhmm(v: Any) -> str:
    w = _when(v)
    return w.strftime("%H:%M") if w is not None else ""


def _item_icu(d: ShiftData) -> str | None:
    """The unit of an ICU stay: the transfer in the shift it happened, the
    ICU stay since the transfer day in the shifts after it, the return to the
    ward in the shift of the step-down and no unit after it (Issue #3555)."""
    from clinosim.modules.document.narrative._icu_stay import icu_hospital_day, icu_step_down_at, icu_transfer_at

    at = icu_transfer_at(d.ctx)
    if at is None or d.window is None:
        return None
    out_at = icu_step_down_at(d.ctx)
    if out_at is not None:
        if d.window[0] <= out_at < d.window[1]:
            return t("nursing_shift_items.icu.step_down", d.lang)
        if out_at < d.window[0]:
            return None
    if d.window[0] <= at < d.window[1]:
        return t("nursing_shift_items.icu.transfer", d.lang)
    if at < d.window[0]:
        return t("nursing_shift_items.icu.in_icu", d.lang, day=icu_hospital_day(d.ctx))
    return None


def _item_pain(d: ShiftData) -> str | None:
    from clinosim.modules.document.narrative.renderers._composers import _pain_label

    scores = [(i, int(s)) for i, v in enumerate(d.readings) if (s := _o(v, "pain_score", None)) is not None]
    if not scores:
        return None
    if _impaired(d):
        # No self-reported NRS from a patient who cannot give one (#3536); the
        # observed equivalent is stated, without inventing findings.
        return t("nursing_shift_items.pain.observed", d.lang)
    peak = max(s for _, s in scores)
    last = scores[-1][1]
    if peak == 0:
        return t("nursing_shift_items.pain.none", d.lang)
    # The progress-note label is empty without a named pain source (#3454); a
    # recorded NRS is still a pain report, named generically.
    pain = _pain_label(d.ctx, progress_vitals_rules(), d.lang) or t("nursing_shift_items.pain.generic", d.lang)
    if peak == last:
        return t("nursing_shift_items.pain.single", d.lang, pain=pain, q=last)
    return t("nursing_shift_items.pain.range", d.lang, pain=pain, peak=peak, last=last)


def _item_fever(d: ShiftData) -> str | None:
    fever_c = progress_vitals_rules().trend.fever_c
    temps = [(i, float(x)) for i, v in enumerate(d.readings) if (x := _o(v, "temperature_celsius", None)) is not None]
    if not temps:
        return None
    peak_i, tmax = max(temps, key=lambda p: (p[1], -p[0]))
    if tmax < fever_c:
        return None
    lang = d.lang
    if not d.doses:
        return t("nursing_shift_items.fever.observed", lang, tmax=f"{tmax:.1f}")
    peak_when = _when(d.readings[peak_i])
    # The dose answering the peak: the first at or after it, else the first of the shift.
    after_peak = [x for x in d.doses if peak_when is not None and x[0] >= peak_when]
    dose = (after_peak or d.doses)[0]
    drug = dose[2]
    later = [x for i, x in temps if (w := _when(d.readings[i])) is not None and w > dose[0]]
    if not later:
        return t("nursing_shift_items.fever.given", lang, tmax=f"{tmax:.1f}", drug=drug)
    after = later[0]
    key = "improved" if after < tmax and after < fever_c else ("lower" if after < tmax else "persisting")
    return t(f"nursing_shift_items.fever.{key}", lang, tmax=f"{tmax:.1f}", drug=drug, after=f"{after:.1f}")


def _item_desaturation(d: ShiftData) -> str | None:
    rules = progress_exam_rules()
    limit = rules.limits.get("spo2")
    if limit is None:
        return None
    when0 = d.window[0] if d.window else None
    low, _, _ = _limit(d.ctx, "spo2", limit, when0 or getattr(d.ctx, "authored_datetime", None))
    if low is None:
        return None
    sats = [(i, float(x)) for i, v in enumerate(d.readings) if (x := _o(v, "spo2", None)) is not None]
    if not sats:
        return None
    low_i, spo2_min = min(sats, key=lambda p: (p[1], -p[0]))
    if spo2_min >= low:
        return None
    lang = d.lang
    r = d.readings[low_i]
    base = {"min": f"{spo2_min:.0f}", "time": _hhmm(r)}
    if _o(r, "on_supplemental_oxygen", False) and _o(r, "oxygen_delivery_device", None) == VENTILATOR_DEVICE:
        return t("nursing_shift_items.desaturation.on_ventilator", lang, **base)
    if _o(r, "on_supplemental_oxygen", False):
        o2 = oxygen_text(_o(r, "oxygen_delivery_device", None), _o(r, "oxygen_flow_rate_lpm", None), lang)
        return t("nursing_shift_items.desaturation.on_oxygen", lang, o2=o2, **base)
    for j, x in sats:
        v = d.readings[j]
        if j > low_i and _o(v, "on_supplemental_oxygen", False):
            o2 = oxygen_text(_o(v, "oxygen_delivery_device", None), _o(v, "oxygen_flow_rate_lpm", None), lang)
            return t("nursing_shift_items.desaturation.oxygen_started", lang, o2=o2, after=f"{x:.0f}", **base)
    return t("nursing_shift_items.desaturation.observed", lang, **base)


def _item_consciousness(d: ShiftData) -> str | None:
    levels = [str(_o(v, "consciousness_level", "") or "") for v in d.readings]
    levels = [x for x in levels if x in _AVPU_ORDER]
    if not levels:
        return None
    worst = max(levels, key=lambda x: _AVPU_ORDER[x])
    if worst == "A":
        return None
    last = levels[-1]
    lang = d.lang
    if last == "A":
        return t("nursing_shift_items.consciousness.transient", lang, w=worst)
    prior = str(_o(d.prior, "consciousness_level", "") or "") if d.prior is not None else ""
    key = "persistent" if prior and prior != "A" else "new"
    return t(f"nursing_shift_items.consciousness.{key}", lang, a=last)


def _item_news2(d: ShiftData) -> str | None:
    scored = [(v, int(sc)) for v in d.readings if (sc := _o(v, "news2_score", None)) is not None]
    if not scored:
        return None
    v, score = scored[-1]
    threshold = news2_urgent_response_threshold()
    if score < threshold:
        return None
    return t("nursing_shift_items.news2.urgent", d.lang, score=score, time=_hhmm(v), threshold=threshold)


def _reason_text(raw: str, lang: str) -> str:
    """A recorded hold / refusal reason in ``lang``: a measured value through the
    YAML patterns, else the shared hold-reason table (as stored when unlisted)."""
    from clinosim.locale.loader import hold_reason_display

    for p in nursing_shift_items_config().hold_reason_patterns:
        m = re.match(p.pattern, raw)
        if m:
            return t(f"nursing_shift_items.hold_reason.{p.phrase}", lang, **m.groupdict())
    return hold_reason_display(raw, lang)


def _item_doses_not_given(d: ShiftData) -> str | None:
    cfg = nursing_shift_items_config()
    seen: set[tuple[str, str]] = set()
    sentences: list[str] = []
    for m in d.not_given:
        status = str(_o(m, "status", "") or "")
        sched = parse_iso_datetime(_o(m, "scheduled_datetime", None) or _o(m, "actual_datetime", None), lenient=True)
        if status == "refused" and sched is not None and _impaired_at(d, sched):
            status = "unable"  # a patient who cannot respond does not refuse (#3536)
        key = administered_drug_key(m)
        if (key, status) in seen:
            continue
        seen.add((key, status))
        drug = administered_drug_name(m, d.lang)
        oral = str(_o(m, "route", "") or "").upper() in cfg.oral_routes
        act = t("nursing_shift_items.not_given.act_oral" if oral else "nursing_shift_items.not_given.act_other", d.lang)
        raw = str((_o(m, "hold_reason", None) if status == "held" else _o(m, "refusal_reason", None)) or "")
        reason = _reason_text(raw, d.lang) if raw else ""
        if status == "unable":
            phrase = "unable_oral" if oral else "unable_other"
        elif status == "held":
            phrase = "held" if reason else "held_plain"
        elif status == "refused":
            phrase = "refused_reason" if reason else "refused"
        else:
            phrase = "unavailable"
        sentences.append(t(f"nursing_shift_items.not_given.{phrase}", d.lang, drug=drug, act=act, reason=reason))
    return "\n".join(sentences) or None


def _item_intake_output(d: ShiftData) -> str | None:
    """The previous calendar day's intake / output balance. The record is one
    per day (no shift split), so only a completed day is stated, labelled as
    such; the shift's own day is never summarised."""
    if d.window is None:
        return None
    prev = d.window[0].date() - timedelta(days=1)
    rec = next(
        (r for r in getattr(d.ctx, "intake_output_records", None) or [] if _record_date(_o(r, "date", None)) == prev),
        None,
    )
    if rec is None:
        return None
    intake = sum(int(_o(rec, k, 0) or 0) for k in ("intake_iv_ml", "intake_oral_ml", "intake_other_ml"))
    urine = int(_o(rec, "output_urine_ml", 0) or 0)
    drain = int(_o(rec, "output_drain_ml", 0) or 0)
    output = urine + drain + int(_o(rec, "output_other_ml", 0) or 0)
    if intake == 0 and output == 0:
        return None
    net = _o(rec, "net_balance_ml", None)
    balance = f"{int(net) if net is not None else intake - output:+d}"
    key = "balance_drain" if drain > 0 else "balance"
    return t(
        f"nursing_shift_items.io.{key}",
        d.lang,
        date=f"{prev.month}/{prev.day}",
        intake=intake,
        output=output,
        urine=urine,
        drain=drain,
        balance=balance,
    )


def _record_date(value: Any) -> date | None:
    parsed = parse_iso_datetime(value, lenient=True)
    return parsed.date() if parsed is not None else None


def _item_devices(d: ShiftData) -> str | None:
    """The devices in place during the shift, each with its routine care: the
    kinds of ``ctx.devices`` (inserted before the shift's end, not removed
    before its day) and the oxygen device of the shift's last reading."""
    if d.window is None:
        return None
    start, end = d.window
    lines: list[str] = []
    in_place = {
        str(_o(x, "kind", "")) for x in getattr(d.ctx, "devices", None) or [] if _device_in_place(x, start, end)
    }
    for dk in nursing_shift_items_config().device_kinds:
        if dk.kind in in_place:
            lines.append(t(f"nursing_shift_items.devices.{dk.kind}", d.lang))
    on_o2 = [v for v in d.readings if _o(v, "on_supplemental_oxygen", None) is not None]
    if on_o2 and _o(on_o2[-1], "on_supplemental_oxygen", False):
        last = on_o2[-1]
        if _o(last, "oxygen_delivery_device", None) == VENTILATOR_DEVICE:
            lines.append(t("nursing_shift_items.devices.ventilator", d.lang))
            return "\n".join(lines)
        o2 = oxygen_text(_o(last, "oxygen_delivery_device", None), _o(last, "oxygen_flow_rate_lpm", None), d.lang)
        lines.append(t("nursing_shift_items.devices.oxygen", d.lang, o2=o2))
    return "\n".join(lines) or None


def _device_in_place(device: Any, start: datetime, end: datetime) -> bool:
    inserted = parse_iso_datetime(_o(device, "start", None), lenient=True)
    if inserted is None or inserted >= end:
        return False
    removed = _record_date(_o(device, "end_date", None))
    return removed is None or start.date() <= removed


def _band(total: int, bands: list[tuple[int, str]]) -> str:
    """The band of ``total``: the first (highest) whose lowest total it reaches."""
    return next((name for low, name in bands if total >= low), bands[-1][1])


def _level(item: str, score: Any, lang: str) -> str | None:
    """The help level of a Barthel item score in ``lang`` (``None`` when the
    score is not one of the item's levels)."""
    if score is None:
        return None
    key = nursing_shift_items_config().adl_levels.get(item, {}).get(int(score))
    return t(f"nursing_shift_items.adl_level.{key}", lang) if key else None


def _as_of(d: ShiftData) -> datetime | None:
    return d.window[1] if d.window else None


def _item_meal(d: ShiftData) -> str | None:
    """The diet in force at the shift's end: nil by mouth, or the diet taken
    orally with the feeding help level and the previous day's oral intake
    when recorded. No intake percentage is stated (the record holds none)."""
    from clinosim.locale.loaders.medical_display import load_diet_supply_route

    if d.window is None:
        return None
    active = diet_order_at(d.ctx, d.window[1])
    if active is None:
        return None
    placed, slug = active
    lang = d.lang
    if load_diet_supply_route().get(slug) == "none":
        npo = t(
            "nursing_shift_items.meal.npo_continued"
            if placed.date() < d.window[0].date()
            else "nursing_shift_items.meal.npo",
            lang,
        )
        # Issue #3552: an oral dose given under the nil-by-mouth order is taken with sips.
        if _oral_dose_given_in(d.ctx, d.window):
            npo += t("nursing_shift_items.meal.npo_sips", lang)
        return npo
    pieces = [t("nursing_shift_items.meal.diet", lang, diet=diet_display(slug, lang))]
    adl = in_force_at(list(getattr(d.ctx, "adl_assessments", None) or []), d.window[1])
    level = _level("feeding", _o(adl, "feeding", None), lang) if adl is not None else None
    if level and _impaired(d):
        # The weekly ADL score can predate the impairment; feeding is stated as
        # full assistance (#3536).
        level = t("nursing_shift_items.adl_level.dependent", lang)
    if level:
        pieces.append(t("nursing_shift_items.meal.feeding", lang, level=level))
    prev = d.window[0].date() - timedelta(days=1)
    rec = next(
        (r for r in getattr(d.ctx, "intake_output_records", None) or [] if _record_date(_o(r, "date", None)) == prev),
        None,
    )
    oral = int(_o(rec, "intake_oral_ml", 0) or 0) if rec is not None else 0
    if oral > 0:
        pieces.append(t("nursing_shift_items.meal.oral_intake", lang, ml=oral))
    return t("list_sep.serial", lang).join(pieces) + t("list_sep.period", lang)


def _oral_dose_given_in(ctx: NarrativeContext, window: tuple[datetime, datetime]) -> bool:
    """True when an oral (``PO``) dose was given in ``window``."""
    for m in ctx.medications or []:
        if str(_o(m, "status", "given") or "given") != "given" or str(_o(m, "route", "") or "") != "PO":
            continue
        when = parse_iso_datetime(_o(m, "actual_datetime", None) or _o(m, "scheduled_datetime", None), lenient=True)
        if when is not None and window[0] <= when < window[1]:
            return True
    return False


def _item_skin(d: ShiftData) -> str | None:
    cfg = nursing_shift_items_config()
    rec = in_force_at(list(getattr(d.ctx, "nursing_risk_assessments", None) or []), _as_of(d))
    braden = _o(rec, "braden_total", None) if rec is not None else None
    if braden is None or int(braden) > cfg.braden_report_at_or_below:
        return None
    band = t(f"morse_band.{_band(int(braden), cfg.braden_bands)}", d.lang)
    key = "prevent" if int(braden) <= cfg.braden_prevention_at_or_below else "observe"
    return t(f"nursing_shift_items.skin.{key}", d.lang, band=band, braden=int(braden))


def _item_mobility(d: ShiftData) -> str | None:
    cfg = nursing_shift_items_config()
    adl = in_force_at(list(getattr(d.ctx, "adl_assessments", None) or []), _as_of(d))
    barthel = _o(adl, "barthel_score", None) if adl is not None else None
    if barthel is None:
        return None
    lang = d.lang
    if _impaired(d):
        # The stored score can predate the impairment; neither it nor its band
        # is quoted for a patient who cannot act for themselves (#3536).
        return t("nursing_shift_items.mobility.impaired", lang)
    band = t(f"barthel_band.{_band(int(barthel), cfg.barthel_bands)}", lang)
    details = []
    for item, label in (("mobility", "mobility"), ("toilet_use", "toilet")):
        level = _level(item, _o(adl, item, None), lang)
        if level:
            details.append(t(f"nursing_shift_items.mobility.{label}", lang, level=level))
    detail = t("list_sep.serial", lang).join(details)
    return t(
        "nursing_shift_items.mobility.line" if detail else "nursing_shift_items.mobility.line_plain",
        lang,
        score=int(barthel),
        band=band,
        detail=detail,
    )


def _item_wound(d: ShiftData) -> str | None:
    """The observation of the site of the encounter's latest surgical-category
    procedure started by the shift's end: the post-operative day with the
    surgical-site observation for a wound, the puncture-site observation for a
    vascular access, the pocket observation for a device implant. The kind and
    the number of days come from the procedure catalog's ``aftercare`` through
    the YAML ``site_observation``; a procedure past its limit states nothing
    (Issue #3556)."""
    if d.window is None:
        return None
    from clinosim.codes.procedures import procedure_aftercare

    cfg = nursing_shift_items_config().site_observation
    enc_id = _o(d.ctx.encounter, "encounter_id", "") or ""
    due: list[tuple[datetime, Any, int, str]] = []
    for p in getattr(d.ctx, "procedures", None) or []:
        if str(_o(p, "category_code", "") or "") != SURGICAL_PROCEDURE or (_o(p, "encounter_id", "") or "") != enc_id:
            continue
        when = parse_iso_datetime(_o(p, "start_datetime", None), lenient=True)
        if when is None or when >= d.window[1]:
            continue
        rule = cfg.get(procedure_aftercare(str(_o(p, "procedure_type", "") or ""))) or cfg["surgical_wound"]
        pod = max((d.window[0].date() - when.date()).days, 0)
        if pod <= rule.max_days:
            due.append((when, p, pod, rule.kind))
    if not due:
        return None
    _when, proc, pod, kind = max(due, key=lambda x: x[0])
    from clinosim.modules.document.narrative.renderers._shared_helpers import resolve_procedure_display

    name = resolve_procedure_display(proc, d.lang)
    base = "nursing_shift_items.wound" if kind == "wound" else f"nursing_shift_items.site.{kind}"
    return t(f"{base}.day0" if pod == 0 else f"{base}.pod", d.lang, name=name, n=pod)


def _item_fall_risk(d: ShiftData) -> str | None:
    rec = in_force_at(list(getattr(d.ctx, "nursing_risk_assessments", None) or []), _as_of(d))
    fall = str(_o(rec, "fall_risk_level", "") or "").lower() if rec is not None else ""
    if fall not in ("high", "moderate"):
        return None
    morse = _o(rec, "morse_total", None)
    key = "nursing_shift_items.fall_risk.with_score" if morse is not None else "nursing_shift_items.fall_risk.plain"
    return t(key, d.lang, level=t(f"morse_band.{fall}", d.lang), morse=morse)


def _day_of_life(d: ShiftData) -> int | None:
    dob = _record_date(_o(getattr(d.ctx, "patient", None), "date_of_birth", None))
    if dob is None or d.window is None:
        return None
    return max((d.window[0].date() - dob).days, 0)


def _item_postpartum(d: ShiftData) -> str | None:
    """A delivery stay's shift after the birth ended (Issue #3664): the
    postpartum day, the obstetric finding of the delivery exam block (the text
    the H&P and the progress note use) and that breastfeeding and voiding are not
    recorded (the record holds none, so none is stated)."""
    from clinosim.modules.document.narrative._delivery import delivery_end, delivery_mode
    from clinosim.modules.document.narrative.renderers._disease_exam import postpartum_obstetric_exam

    birth = delivery_end(d.ctx)
    if d.window is None or birth is None or delivery_mode(d.ctx) is None:
        return None
    end = d.window[1].replace(tzinfo=None)
    if end <= birth.replace(tzinfo=None):
        return None
    return t(
        "nursing_shift_items.postpartum.line",
        d.lang,
        day=(end.date() - birth.date()).days,
        finding=postpartum_obstetric_exam(d.ctx),
    )


def _item_newborn_care(d: ShiftData) -> str | None:
    dol = _day_of_life(d)
    if dol is None:
        return None
    return t("nursing_shift_items.newborn.care", d.lang, day=dol)


def _item_newborn_weight(d: ShiftData) -> str | None:
    kg = _o(getattr(d.ctx, "patient", None), "weight_kg", None)
    if kg is None:
        return None
    return t("nursing_shift_items.newborn.birth_weight", d.lang, kg=f"{float(kg):g}")


def _item_newborn_jaundice(d: ShiftData) -> str | None:
    from clinosim.modules.document.narrative.context import newborn_workup_known_at

    workup = getattr(d.ctx, "newborn_workup", None) or {}
    series = (newborn_workup_known_at(workup, d.window[1] if d.window else None) or {}).get("bilirubin_series") or []
    if not series:
        return None
    last = max(series, key=lambda e: str(e.get("timestamp") or ""))
    # Stated once, in the shift that holds the measurement: a later shift with no
    # new reading does not repeat it as an ongoing observation (Issue #3564).
    measured = parse_iso_datetime(last.get("timestamp"), lenient=True)
    if d.window is not None and measured is not None:
        if not (d.window[0] <= measured.replace(tzinfo=None) < d.window[1].replace(tzinfo=None)):
            return None
    elif last.get("day") != _day_of_life(d):
        return None
    return t(
        "nursing_shift_items.newborn.jaundice",
        d.lang,
        v=f"{float(last['value_mg_dl']):.1f}",
        day=last.get("day") if last.get("day") is not None else "",
    )


ITEM_FUNCTIONS: dict[str, Callable[[ShiftData], str | None]] = {
    "icu": _item_icu,
    "pain": _item_pain,
    "fever": _item_fever,
    "desaturation": _item_desaturation,
    "consciousness": _item_consciousness,
    "news2": _item_news2,
    "doses_not_given": _item_doses_not_given,
    "intake_output": _item_intake_output,
    "devices": _item_devices,
    "meal": _item_meal,
    "skin": _item_skin,
    "mobility": _item_mobility,
    "wound": _item_wound,
    "postpartum": _item_postpartum,
    "fall_risk": _item_fall_risk,
    "newborn_care": _item_newborn_care,
    "newborn_weight": _item_newborn_weight,
    "newborn_jaundice": _item_newborn_jaundice,
}


def _shift_doses(
    ctx: NarrativeContext, window: tuple[datetime, datetime] | None, lang: str
) -> list[tuple[datetime, str, str]]:
    antipyretics = set(nursing_shift_items_config().antipyretic_drug_keys)
    out: list[tuple[datetime, str, str]] = []
    if window is None:
        return out
    for m in ctx.medications or []:
        if str(_o(m, "status", "given") or "given") != "given":
            continue
        when = parse_iso_datetime(_o(m, "actual_datetime", None) or _o(m, "scheduled_datetime", None), lenient=True)
        key = administered_drug_key(m)
        if when is None or not key or not (window[0] <= when < window[1]):
            continue
        if key in antipyretics:
            out.append((when, key, administered_drug_name(m, lang)))
    out.sort(key=lambda x: x[0])
    return out


_NOT_GIVEN = ("held", "refused", "not_available")


def _shift_not_given(ctx: NarrativeContext, window: tuple[datetime, datetime] | None) -> list[Any]:
    """The MAR rows scheduled in the shift window (which ends at the authored
    time) that were held, refused or not available, in time order."""
    if window is None:
        return []
    rows: list[tuple[datetime, Any]] = []
    for m in ctx.medications or []:
        if str(_o(m, "status", "given") or "given") not in _NOT_GIVEN:
            continue
        when = parse_iso_datetime(_o(m, "scheduled_datetime", None) or _o(m, "actual_datetime", None), lenient=True)
        if when is None or not (_o(m, "drug_name", None) or _o(m, "medication", None)):
            continue
        if window[0] <= when < window[1]:
            rows.append((when, m))
    rows.sort(key=lambda r: r[0])
    return [m for _, m in rows]


def nursing_shift_item_lines(
    ctx: NarrativeContext,
    lang: str,
    readings: list[Any],
    window: tuple[datetime, datetime] | None,
) -> list[tuple[str, str]]:
    """``(text, fact_tag)`` of each registry item the shift's record shows, in
    the YAML order."""
    prior: Any | None = None
    if window is not None:
        before = [(w, v) for v in ctx.vitals or [] if (w := _when(v)) is not None and w < window[0]]
        prior = max(before, key=lambda p: p[0])[1] if before else None
    data = ShiftData(ctx, lang, readings, prior, window, _shift_doses(ctx, window, lang), _shift_not_given(ctx, window))
    neonate = is_neonate(ctx)
    out: list[tuple[str, str]] = []
    for item in nursing_shift_items_config().items:
        if (neonate and item.skip_neonate) or (item.only_neonate and not neonate):
            continue
        if item.only_postpartum and delivery_mode(ctx) is None:
            continue
        text = ITEM_FUNCTIONS[item.id](data)
        if text:
            out.append((text, item.fact))
    return out
