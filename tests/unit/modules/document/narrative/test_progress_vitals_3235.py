"""Progress-note Subjective / Objective from the vitals of the note's period
(Issues #3235, #3247): the latest value of each vital with the period's
abnormal extremes, oxygen therapy, trends from whole periods, no NRS for a
patient who cannot self-report, and the pain named by its site."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from clinosim.modules.document.narrative.renderers._composers import (
    compose_progress_subjective_from_state,
    compose_today_vitals_line,
)

pytestmark = pytest.mark.unit

_ADM = datetime(2026, 5, 1, 10, 0)


def _ctx(vitals: list[dict], *, day: int = 1, lang: str = "ja", disease: str = "sepsis", authored=None):
    return SimpleNamespace(
        target_lang=lang,
        vitals=vitals,
        day_index=day,
        los_days=6,
        encounter={"encounter_id": "E1", "admission_datetime": _ADM},
        patient={"date_of_birth": "1950-01-01"},
        disease_protocol=SimpleNamespace(disease_id=disease),
        clinical_course_archetype="smooth_recovery",
        authored_datetime=authored,
    )


def _v(day: int, hour: int, **fields) -> dict:
    return {"timestamp": datetime(2026, 5, 1 + day, hour, 0).isoformat(), **fields}


def test_bp_from_a_later_reading_when_the_first_lacks_it() -> None:
    vitals = [
        _v(1, 2, heart_rate=109, spo2=97.0),
        _v(1, 8, systolic_bp=118, diastolic_bp=70, heart_rate=96, temperature_celsius=37.1),
    ]
    line = compose_today_vitals_line(_ctx(vitals, lang="en"))
    assert "BP 118/70 mmHg" in line
    assert "HR 96" in line  # the latest heart rate, not the first


def test_abnormal_extreme_of_the_day_is_printed() -> None:
    vitals = [
        _v(1, 2, temperature_celsius=38.8, heart_rate=118, systolic_bp=120, diastolic_bp=70, spo2=96.0),
        _v(1, 14, temperature_celsius=37.2, heart_rate=92, systolic_bp=122, diastolic_bp=72, spo2=97.0),
    ]
    ja = compose_today_vitals_line(_ctx(vitals))
    assert "T 37.2°C" in ja and "最高体温 38.8°C" in ja and "HR 最大 118" in ja
    en = compose_today_vitals_line(_ctx(vitals, lang="en"))
    assert "Tmax 38.8°C" in en and "HR max 118 bpm" in en
    assert not any("぀" <= ch <= "鿿" for ch in en)


def test_extreme_equal_to_latest_is_not_repeated() -> None:
    vitals = [_v(1, 2, temperature_celsius=37.0), _v(1, 14, temperature_celsius=38.6)]
    line = compose_today_vitals_line(_ctx(vitals, lang="en"))
    assert "T 38.6°C" in line and "Tmax" not in line


@pytest.mark.parametrize(
    ("lang", "expected"), [("en", "SpO2 95% (nasal cannula 3 L/min)"), ("ja", "SpO2 95% (鼻カニューラ 3 L/分)")]
)
def test_oxygen_in_objective(lang: str, expected: str) -> None:
    vitals = [
        _v(
            1,
            8,
            spo2=95.0,
            on_supplemental_oxygen=True,
            oxygen_flow_rate_lpm=3.0,
            oxygen_delivery_device="nasal_cannula",
        )
    ]
    assert expected in compose_today_vitals_line(_ctx(vitals, lang=lang))


def test_room_air_and_weaning_in_objective() -> None:
    vitals = [
        _v(
            1,
            2,
            spo2=93.0,
            on_supplemental_oxygen=True,
            oxygen_flow_rate_lpm=2.0,
            oxygen_delivery_device="nasal_cannula",
        ),
        _v(1, 14, spo2=96.0),
    ]
    line = compose_today_vitals_line(_ctx(vitals, lang="en"))
    assert "SpO2 96% (RA)" in line and "weaned off supplemental O2" in line


def test_window_up_to_the_authored_time() -> None:
    # Note authored 2026-05-02 10:00: readings of (05-01 10:00, 05-02 10:00].
    vitals = [_v(0, 12, heart_rate=80), _v(1, 9, heart_rate=90), _v(1, 15, heart_rate=130)]
    line = compose_today_vitals_line(_ctx(vitals, lang="en", authored=datetime(2026, 5, 2, 10, 0)))
    assert "HR 90" in line and "130" not in line


def test_no_reading_before_the_authored_time_is_stated() -> None:
    vitals = [_v(0, 12, heart_rate=80)]
    line = compose_today_vitals_line(_ctx(vitals, day=0, lang="en", authored=_ADM))
    assert "80" not in line and "No vital signs recorded" in line


def test_continuous_fever_is_persistent_by_previous_day_maximum() -> None:
    # Previous day: first reading afebrile, later 38.5; today 38.4.
    vitals = [
        _v(0, 12, temperature_celsius=37.0),
        _v(0, 20, temperature_celsius=38.5),
        _v(1, 6, temperature_celsius=38.4),
    ]
    text = compose_progress_subjective_from_state(_ctx(vitals))
    assert "持続" in text and "出現" not in text


def test_fever_later_in_the_day_is_reported() -> None:
    vitals = [
        _v(0, 12, temperature_celsius=36.8),
        _v(1, 6, temperature_celsius=36.9),
        _v(1, 18, temperature_celsius=38.7),
    ]
    text = compose_progress_subjective_from_state(_ctx(vitals, lang="en"))
    assert "New-onset fever 38.7" in text


@pytest.mark.parametrize("lang", ["en", "ja"])
def test_no_nrs_when_avpu_is_p(lang: str) -> None:
    vitals = [
        _v(0, 12, pain_score=6, consciousness_level="A"),
        _v(1, 6, pain_score=6, consciousness_level="P"),
    ]
    text = compose_progress_subjective_from_state(_ctx(vitals, lang=lang))
    assert "NRS" not in text
    assert "AVPU P" in text


def test_pain_named_by_disease_site() -> None:
    vitals = [_v(0, 12, pain_score=7), _v(1, 6, pain_score=7)]
    ja = compose_progress_subjective_from_state(_ctx(vitals, disease="hip_fracture"))
    assert "股関節部痛持続 (NRS 7)" in ja
    en = compose_progress_subjective_from_state(_ctx(vitals, lang="en", disease="acute_appendicitis"))
    assert "Persistent right lower quadrant pain (NRS 7)" in en


def test_pain_without_site_for_a_disease_without_one() -> None:
    vitals = [_v(0, 12, pain_score=7), _v(1, 6, pain_score=7)]
    assert "疼痛持続 (NRS 7)" in compose_progress_subjective_from_state(_ctx(vitals, disease="sepsis"))


def test_fever_of_exactly_38_is_an_extreme() -> None:
    vitals = [_v(1, 2, temperature_celsius=38.0), _v(1, 14, temperature_celsius=37.0)]
    assert "Tmax 38.0°C" in compose_today_vitals_line(_ctx(vitals, lang="en"))
