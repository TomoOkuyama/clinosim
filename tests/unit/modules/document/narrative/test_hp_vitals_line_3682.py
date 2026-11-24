"""The H&P vitals line quotes the oxygen of an SpO2 taken on oxygen and the
admission set, not one monitor-only reading (Issue #3682)."""

from __future__ import annotations

from datetime import datetime

import pytest

from clinosim.modules.document.narrative.renderers._composers import compose_pe_vitals_line, pe_vitals_reading
from tests.unit.modules.document.narrative.test_progress_exam_course_3235_3247 import _ctx, _v

pytestmark = pytest.mark.unit

_TRIAGE = {"systolic_bp": 145, "diastolic_bp": 76, "temperature_celsius": 37.4, "respiratory_rate": 22, "spo2": 94.0}
_MONITOR = {
    "heart_rate": 109,
    "spo2": 90.8,
    "on_supplemental_oxygen": True,
    "oxygen_delivery_device": "non_rebreather",
    "oxygen_flow_rate_lpm": 8.0,
}


def _ctx_for(vitals: list[dict], lang: str = "en"):
    ctx = _ctx(vitals, day=0, lang=lang)
    ctx.authored_datetime = datetime(2026, 5, 1, 21, 0)
    return ctx


def test_monitor_only_reading_on_oxygen_shows_device_and_carries_the_admission_set() -> None:
    vitals = [_v(0, 11, **_TRIAGE, on_supplemental_oxygen=False), _v(0, 18, **_MONITOR)]
    line = compose_pe_vitals_line(_ctx_for(vitals))
    assert "SpO2 91% (non-rebreather 8 L/min)" in line or "SpO2 91% (non-rebreather mask 8 L/min)" in line
    assert "BP 145/76 mmHg" in line and "T 37.4°C" in line and "RR 22/min" in line and "HR 109/min" in line


def test_room_air_patient_renders_ra() -> None:
    vitals = [_v(0, 11, **_TRIAGE, heart_rate=90, on_supplemental_oxygen=False)]
    assert "SpO2 94% (RA)" in compose_pe_vitals_line(_ctx_for(vitals))


def test_ja_line_names_the_oxygen_device() -> None:
    vitals = [_v(0, 11, **_TRIAGE, on_supplemental_oxygen=False), _v(0, 18, **_MONITOR)]
    line = compose_pe_vitals_line(_ctx_for(vitals, "ja"))
    assert "リザーバー付き酸素マスク 8 L/分" in line and "BP 145/76 mmHg" in line


def test_readings_after_the_authored_time_are_not_quoted() -> None:
    vitals = [_v(0, 11, **_TRIAGE, on_supplemental_oxygen=False), _v(0, 23, **_MONITOR)]
    line = compose_pe_vitals_line(_ctx_for(vitals))
    assert "(RA)" in line and "non-rebreather" not in line and "HR" not in line


def test_no_vitals_is_empty() -> None:
    assert compose_pe_vitals_line(_ctx_for([])) == ""
    assert pe_vitals_reading(_ctx_for([])) is None
