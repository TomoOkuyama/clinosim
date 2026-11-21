"""The data-driven nursing items of a shift note (Issue #3478).

``reference_data/nursing_shift_items.yaml`` lists the items in order; each id
names a function below that reads the readings (and MAR) of the note's shift
window and returns ``(text, fact_tag)`` or ``None`` when the shift's record
does not show the item. Nothing is stated that the record of the shift does not
hold, and nothing recorded after the note's authored time (the window ends
there).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from clinosim.codes.drugs import drug_display, drug_key
from clinosim.datafiles import load_validated_yaml
from clinosim.locale.i18n import t
from clinosim.modules._shared import get_attr_or_key as _o
from clinosim.modules._shared import strip_protocol_prefix
from clinosim.modules.document.narrative._narrative_interpretation_thresholds import progress_vitals_rules
from clinosim.modules.document.narrative._narrative_utils import is_neonate
from clinosim.modules.document.narrative._progress_exam import _limit, progress_exam_rules
from clinosim.modules.document.narrative._vitals_line import oxygen_text
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


class NursingShiftItems(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[NursingShiftItem] = Field(min_length=1)
    antipyretic_drug_keys: list[str] = Field(min_length=1)

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


def _when(v: Any) -> datetime | None:
    return parse_iso_datetime(_o(v, "timestamp", None), lenient=True)


def _hhmm(v: Any) -> str:
    w = _when(v)
    return w.strftime("%H:%M") if w is not None else ""


def _item_pain(d: ShiftData) -> str | None:
    from clinosim.modules.document.narrative.renderers._composers import _pain_label

    scores = [(i, int(s)) for i, v in enumerate(d.readings) if (s := _o(v, "pain_score", None)) is not None]
    if not scores:
        return None
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


ITEM_FUNCTIONS: dict[str, Callable[[ShiftData], str | None]] = {
    "pain": _item_pain,
    "fever": _item_fever,
    "desaturation": _item_desaturation,
    "consciousness": _item_consciousness,
    "news2": _item_news2,
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
        name = _o(m, "drug_name", None) or _o(m, "medication", None)
        if when is None or not name or not (window[0] <= when < window[1]):
            continue
        bare, _ = strip_protocol_prefix(str(name))
        key = drug_key(bare)
        if bare and key in antipyretics:
            out.append((when, key, drug_display(key, lang) or bare))
    out.sort(key=lambda x: x[0])
    return out


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
    data = ShiftData(ctx, lang, readings, prior, window, _shift_doses(ctx, window, lang))
    neonate = is_neonate(ctx)
    out: list[tuple[str, str]] = []
    for item in nursing_shift_items_config().items:
        if neonate and item.skip_neonate:
            continue
        text = ITEM_FUNCTIONS[item.id](data)
        if text:
            out.append((text, item.fact))
    return out
