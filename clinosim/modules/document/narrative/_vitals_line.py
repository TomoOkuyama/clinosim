"""One formatter for vital-signs one-liners (Issue #2523).

Each narrative surface summarises a vitals record in its own house style
(field order, separators, units, integer vs raw values, a room-air marker).
The styles below name those conventions; :func:`format_vitals_line` renders
any of them, so a change to how a vital is read or shown is made once.

Placeholders available to a style's formats: the raw values ``{sbp}``
``{dbp}`` ``{hr}`` ``{rr}`` ``{spo2}`` ``{temp}``; integer forms ``{sbp_i}``
``{dbp_i}`` ``{hr_i}`` ``{rr_i}``; float forms ``{spo2_f}`` ``{temp_f}``; and
the localized units ``{hr_unit}`` ``{rr_unit}``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from clinosim.locale.i18n import t
from clinosim.modules._shared import get_attr_or_key
from clinosim.timeutil import parse_iso_datetime

__all__ = [
    "LLM_ARRIVAL",
    "LLM_DAY",
    "NURSING_SHIFT",
    "PHYSICAL_EXAM",
    "PROGRESS_OBJECTIVE",
    "VitalsLineStyle",
    "format_vitals_line",
    "latest_vitals_set",
    "vitals_in_window",
]

_FIELDS = {
    "sbp": "systolic_bp",
    "dbp": "diastolic_bp",
    "hr": "heart_rate",
    "rr": "respiratory_rate",
    "spo2": "spo2",
    "temp": "temperature_celsius",
}
# Recorded with the SpO2 reading they qualify.
_OXYGEN_FIELDS = ("on_supplemental_oxygen", "oxygen_delivery_device", "oxygen_flow_rate_lpm")


@dataclass(frozen=True)
class VitalsLineStyle:
    """How one surface writes a vitals line.

    ``order`` lists the vitals shown (``bp`` ``hr`` ``rr`` ``spo2`` ``temp``);
    a vital appears only when its value is recorded (blood pressure needs
    both values unless ``systolic_only_format`` is set). ``room_air_format``,
    when set, replaces the SpO2 format for a reading without supplemental
    oxygen.
    """

    order: tuple[str, ...]
    formats: dict[str, str]
    separator: str
    systolic_only_format: str | None = None
    room_air_format: str | None = None


# Inpatient progress-note objective and the outpatient vitals line.
PROGRESS_OBJECTIVE = VitalsLineStyle(
    order=("bp", "hr", "rr", "spo2", "temp"),
    formats={
        "bp": "BP {sbp_i}/{dbp_i} mmHg",
        "hr": "HR {hr_i} {hr_unit}",
        "rr": "RR {rr_i} {rr_unit}",
        "spo2": "SpO2 {spo2:.0f}%",
        "temp": "T {temp:.1f}°C",
    },
    separator=", ",
)

# Physical-examination vitals, as in JP acute-care admission notes:
# "BP 130/80 mmHg, HR 88/min, T 37.5°C, SpO2 96% (RA), RR 20/min".
PHYSICAL_EXAM = VitalsLineStyle(
    order=("bp", "hr", "temp", "spo2", "rr"),
    formats={
        "bp": "BP {sbp_i}/{dbp_i} mmHg",
        "hr": "HR {hr_i}/min",
        "temp": "T {temp:.1f}°C",
        "spo2": "SpO2 {spo2:.0f}%",
        "rr": "RR {rr_i}/min",
    },
    separator=", ",
    room_air_format="SpO2 {spo2:.0f}% (RA)",
)

# LLM prompt context: today's readings, values as recorded.
LLM_DAY = VitalsLineStyle(
    order=("temp", "hr", "bp", "rr", "spo2"),
    formats={
        "temp": "T {temp}°C",
        "hr": "HR {hr}",
        "bp": "BP {sbp}/{dbp}",
        "rr": "RR {rr}",
        "spo2": "SpO2 {spo2}%",
    },
    separator=" / ",
)

# LLM prompt context: arrival vitals (ED), values as recorded.
LLM_ARRIVAL = VitalsLineStyle(
    order=("temp", "hr", "bp", "spo2"),
    formats={
        "temp": "T {temp}°C",
        "hr": "HR {hr}",
        "bp": "BP {sbp}/{dbp}",
        "spo2": "SpO2 {spo2}%",
    },
    separator=" / ",
    systolic_only_format="BP {sbp}",
)

# Nursing shift note status line.
NURSING_SHIFT = VitalsLineStyle(
    order=("bp", "hr", "spo2", "temp"),
    formats={
        "bp": "BP {sbp_i}/{dbp_i}",
        "hr": "HR {hr_i}",
        "spo2": "SpO2 {spo2_f:.0f}%",
        "temp": "T {temp_f:.1f}°C",
    },
    separator=", ",
)


class _Values(dict):
    """Placeholder values, converted on first use (a style that never shows
    ``{sbp_i}`` never calls ``int`` on the systolic value)."""

    def __init__(self, raw: dict[str, Any], lang: str) -> None:
        super().__init__(raw)
        self._lang = lang

    def __missing__(self, key: str) -> Any:
        if key == "hr_unit":
            value: Any = t("narrative_text.vital_unit.hr", self._lang)
        elif key == "rr_unit":
            value = t("narrative_text.vital_unit.rr", self._lang)
        elif key.endswith("_i"):
            value = int(self[key[:-2]])
        elif key.endswith("_f"):
            value = float(self[key[:-2]])
        else:
            raise KeyError(key)
        self[key] = value
        return value


def format_vitals_line(vitals: Any, style: VitalsLineStyle, lang: str) -> str:
    """The vitals record ``vitals`` (mapping or object) in ``style``; ``""``
    when none of the style's vitals is recorded."""
    values = _Values({name: get_attr_or_key(vitals, attr, None) for name, attr in _FIELDS.items()}, lang)
    parts: list[str] = []
    for vital in style.order:
        fmt: str | None
        if vital == "bp":
            if values["sbp"] and values["dbp"]:
                fmt = style.formats["bp"]
            elif values["sbp"] and style.systolic_only_format:
                fmt = style.systolic_only_format
            else:
                fmt = None
        elif not values[vital]:
            fmt = None
        elif vital == "spo2" and style.room_air_format and not get_attr_or_key(vitals, "on_supplemental_oxygen", False):
            fmt = style.room_air_format
        else:
            fmt = style.formats[vital]
        if fmt is not None:
            parts.append(fmt.format_map(values))
    return style.separator.join(parts)


def vitals_in_window(vitals: list[Any], start: datetime, end: datetime) -> list[Any]:
    """The readings timed in ``[start, end)``, oldest first (Issue #3239)."""
    timed: list[tuple[datetime, int, Any]] = []
    for i, v in enumerate(vitals or []):
        ts = parse_iso_datetime(get_attr_or_key(v, "timestamp", None), lenient=True)
        if ts is not None and start <= ts < end:
            timed.append((ts, i, v))
    timed.sort(key=lambda x: (x[0], x[1]))
    return [v for _, _, v in timed]


def latest_vitals_set(readings: list[Any]) -> dict[str, Any]:
    """The latest recorded value of each vital over ``readings`` (oldest
    first), as one record :func:`format_vitals_line` reads (with the latest
    AVPU level). A reading often carries only some vitals; the oxygen fields
    come from the reading that gave the SpO2."""
    merged: dict[str, Any] = {}
    for attr in (*_FIELDS.values(), "consciousness_level"):
        for v in reversed(readings):
            value = get_attr_or_key(v, attr, None)
            if value is not None:
                merged[attr] = value
                if attr == "spo2":
                    for o2 in _OXYGEN_FIELDS:
                        merged[o2] = get_attr_or_key(v, o2, None)
                break
    return merged
