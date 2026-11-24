"""The discharge summary's hospital course states a positive culture (specimen,
organism, collection date) and the last vital signs with the oxygen status
(Issue #3679), each only when the record has the facts."""

from __future__ import annotations

from datetime import datetime

import pytest

from clinosim.modules.document.narrative.renderers.section_builders.discharge_summary import compose_hospital_course
from tests.unit.modules.document.narrative.test_hospital_course_3246 import _ctx

pytestmark = pytest.mark.unit

_BLOOD_POS = {
    "encounter_id": "enc-3246",
    "specimen": "blood",
    "specimen_snomed": "119297000",
    "collected_datetime": datetime(2025, 12, 5, 9, 0),
    "growth": True,
    "organism_snomed": "56415008",
}
_BLOOD_NEG = {**_BLOOD_POS, "growth": False, "organism_snomed": ""}
_DISCHARGE = datetime(2025, 12, 10, 10, 0)


def _course(lang: str, **fields) -> str:
    ctx = _ctx(lang, **fields)
    ctx.authored_datetime = _DISCHARGE
    return compose_hospital_course(ctx)[0]


def _v(hour_before: float, **fields) -> dict:
    from datetime import timedelta

    return {"timestamp": (_DISCHARGE - timedelta(hours=hour_before)).isoformat(), **fields}


def test_positive_culture_en() -> None:
    text = _course("en", microbiology=[_BLOOD_POS])
    assert "2025-12-05" in text and "culture" in text.lower() and "Klebsiella pneumoniae" in text


def test_positive_culture_ja() -> None:
    text = _course("ja", microbiology=[_BLOOD_POS])
    assert "2025-12-05" in text and "培養" in text and "肺炎桿菌" in text


def test_negative_or_no_culture_writes_nothing() -> None:
    for micro in ([_BLOOD_NEG], []):
        text = _course("en", microbiology=micro)
        assert "culture" not in text.lower()


def test_referral_letter_course_is_unchanged() -> None:
    ctx = _ctx("en", microbiology=[_BLOOD_POS], vitals=[_v(2, spo2=97.0, on_supplemental_oxygen=False)])
    ctx.authored_datetime = _DISCHARGE
    text = compose_hospital_course(ctx, with_results=False)[0]
    assert "culture" not in text.lower() and "Vital signs at discharge" not in text


def test_discharge_vitals_use_latest_readings_and_oxygen_device() -> None:
    vitals = [
        _v(
            20,
            systolic_bp=150,
            diastolic_bp=90,
            spo2=90.0,
            on_supplemental_oxygen=True,
            oxygen_delivery_device="simple_mask",
            oxygen_flow_rate_lpm=6.0,
        ),
        _v(
            3,
            spo2=98.0,
            heart_rate=72,
            on_supplemental_oxygen=True,
            oxygen_delivery_device="simple_mask",
            oxygen_flow_rate_lpm=4.0,
        ),
    ]
    text = _course("en", vitals=vitals)
    assert "Vital signs at discharge" in text
    assert "BP 150/90 mmHg" in text and "HR 72" in text and "SpO2 98% (" in text and "4 L/min" in text


def test_discharge_vitals_room_air_and_ja() -> None:
    vitals = [_v(3, spo2=97.0, heart_rate=70, on_supplemental_oxygen=False)]
    assert "SpO2 97% (RA)" in _course("en", vitals=vitals)
    assert "退院時のバイタルサイン" in _course("ja", vitals=vitals)


def test_readings_outside_the_last_day_or_after_the_note_are_not_quoted() -> None:
    vitals = [_v(40, spo2=88.0, on_supplemental_oxygen=False), _v(-2, spo2=99.0, on_supplemental_oxygen=False)]
    assert "Vital signs at discharge" not in _course("en", vitals=vitals)


def test_no_readings_omits_the_sentence() -> None:
    assert "Vital signs at discharge" not in _course("en")
