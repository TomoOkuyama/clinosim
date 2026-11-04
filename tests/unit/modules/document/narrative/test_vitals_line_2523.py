"""Vitals one-liner styles (Issue #2523): each pins the format its surface
produced before the formatter was shared."""

from __future__ import annotations

from clinosim.locale.i18n import t
from clinosim.modules.document.narrative._vitals_line import (
    LLM_ARRIVAL,
    LLM_DAY,
    NURSING_SHIFT,
    PHYSICAL_EXAM,
    PROGRESS_OBJECTIVE,
    format_vitals_line,
)

_V = {
    "systolic_bp": 130.0,
    "diastolic_bp": 80,
    "heart_rate": 88.4,
    "respiratory_rate": 20,
    "spo2": 96.2,
    "temperature_celsius": 37.46,
    "on_supplemental_oxygen": False,
}


def test_progress_objective() -> None:
    hr, rr = t("narrative_text.vital_unit.hr", "ja"), t("narrative_text.vital_unit.rr", "ja")
    assert (
        format_vitals_line(_V, PROGRESS_OBJECTIVE, "ja")
        == f"BP 130/80 mmHg, HR 88 {hr}, RR 20 {rr}, SpO2 96%, T 37.5°C"
    )


def test_physical_exam_marks_room_air() -> None:
    assert (
        format_vitals_line(_V, PHYSICAL_EXAM, "en") == "BP 130/80 mmHg, HR 88/min, T 37.5°C, SpO2 96% (RA), RR 20/min"
    )
    on_o2 = dict(_V, on_supplemental_oxygen=True)
    assert "SpO2 96%," in format_vitals_line(on_o2, PHYSICAL_EXAM, "en")


def test_llm_styles_keep_recorded_values() -> None:
    assert format_vitals_line(_V, LLM_DAY, "en") == "T 37.46°C / HR 88.4 / BP 130.0/80 / RR 20 / SpO2 96.2%"
    no_dbp = dict(_V, diastolic_bp=None)
    assert format_vitals_line(no_dbp, LLM_ARRIVAL, "en") == "T 37.46°C / HR 88.4 / BP 130.0 / SpO2 96.2%"
    assert "BP" not in format_vitals_line(no_dbp, LLM_DAY, "en")


def test_nursing_shift() -> None:
    assert format_vitals_line(_V, NURSING_SHIFT, "en") == "BP 130/80, HR 88, SpO2 96%, T 37.5°C"


def test_unrecorded_vitals_are_left_out() -> None:
    assert format_vitals_line({"heart_rate": 70}, NURSING_SHIFT, "en") == "HR 70"
    assert format_vitals_line({}, PROGRESS_OBJECTIVE, "en") == ""
    assert format_vitals_line(None, LLM_DAY, "en") == ""
