"""Newborn bilirubin wording and the newborn H&P / shift / discharge content (Issues #3564, #3565).

The newborn bilirubin series is transcutaneous (LOINC 58941-6): every newborn
document names it so, a later note does not restate an earlier day's value as
current, and a shift states a reading once. The H&P gives an impression and a
plan from the record (no resuscitation-status line for a healthy newborn),
the shift note says what the record does not hold, and the discharge summary
states the last bilirubin and that discharge weight and feeding are not
recorded.
"""

from __future__ import annotations

import re
from datetime import datetime

import pytest

from clinosim.modules.document.narrative.renderers._composers import compose_progress_subjective_from_state
from clinosim.modules.document.narrative.renderers.section_builders.assessment_and_plan import (
    build_assessment_and_plan,
)
from clinosim.modules.document.narrative.renderers.section_builders.discharge_summary import compose_hospital_course
from clinosim.modules.document.narrative.template_generator import TemplateNarrativeGenerator
from clinosim.types.document import DocumentType
from tests.unit.modules.document.narrative.test_newborn_documents_3260 import _ctx
from tests.unit.modules.document.narrative.test_nursing_shift_assessments_3481 import _baby as _shift_baby
from tests.unit.modules.document.narrative.test_nursing_shift_assessments_3481 import _note as _shift_note

pytestmark = pytest.mark.unit

_GEN = TemplateNarrativeGenerator()
_CJK = re.compile(r"[぀-ヿ㐀-鿿]")
_SHIFT_BILI = {
    "bilirubin_series": [
        {"timestamp": "2026-09-01T10:00:00", "day": 1, "value_mg_dl": 7.8},
        {"timestamp": "2026-09-02T10:00:00", "day": 2, "value_mg_dl": 10.0},
    ],
    "event_times": {},
}


def _progress(lang: str, day: int, hour: int = 12):
    ctx = _ctx(lang, day_index=day, authored=datetime(2026, 1, 26 + day, hour, 0))
    ctx.document_type = DocumentType.PROGRESS_NOTE
    return ctx


@pytest.mark.parametrize("lang", ["ja", "en"])
def test_progress_note_names_the_series_transcutaneous(lang: str) -> None:
    text = compose_progress_subjective_from_state(_progress(lang, 2))
    assert ("経皮ビリルビン" if lang == "ja" else "transcutaneous bilirubin") in text
    assert "総ビリルビン" not in text and "total bilirubin" not in text


def test_progress_note_after_the_last_measurement_states_it_as_the_last_one() -> None:
    ctx = _progress("ja", 4)
    ja = compose_progress_subjective_from_state(ctx)
    assert "経皮ビリルビンの最終測定は日齢3の 12.2 mg/dL (以後の測定なし)" in ja
    assert "日齢3の測定" not in ja
    en = compose_progress_subjective_from_state(_progress("en", 4))
    assert "last transcutaneous bilirubin was 12.2 mg/dL on day of life 3 (no measurement since)" in en
    # The day of the measurement still reads as today's value.
    assert "(日齢3の測定)" in compose_progress_subjective_from_state(_progress("ja", 3))


@pytest.mark.parametrize("lang", ["ja", "en"])
def test_discharge_summary_states_the_last_bilirubin_once_with_its_day(lang: str) -> None:
    ctx = _ctx(lang, day_index=5, authored=datetime(2026, 1, 31, 10, 0))
    ctx.document_type = DocumentType.DISCHARGE_SUMMARY
    text, _ = compose_hospital_course(ctx)
    if lang == "ja":
        assert text.count("経皮ビリルビン最終測定値 12.2 mg/dL (日齢3)") == 1
        assert "総ビリルビン" not in text and "最高値" not in text
        assert "退院時体重、哺乳方法は記録なし。" in text
    else:
        assert text.count("last transcutaneous bilirubin 12.2 mg/dL (day of life 3)") == 1
        assert "total bilirubin" not in text
        assert "Discharge weight and feeding method not recorded." in text
        assert not _CJK.search(text)


def test_shift_note_states_a_reading_in_its_own_shift_only() -> None:
    day1 = _shift_note(_shift_baby("ja", 1, newborn_workup=_SHIFT_BILI))[0]
    assert "日齢1の経皮ビリルビン測定値 7.8 mg/dL" in day1
    # Day 1 evening and night: no new reading, so no repeat of the day-1 value.
    for shift, hour in (("evening", 23), ("night", 5)):
        later = _shift_note(
            _shift_baby("ja", 1, shift=shift, newborn_workup=_SHIFT_BILI, authored_datetime=datetime(2026, 9, 1, hour))
        )[0]
        assert "ビリルビン" not in later, (shift, later)
    day3 = _shift_note(_shift_baby("ja", 3, newborn_workup=_SHIFT_BILI))[0]
    assert "ビリルビン" not in day3 and "7.8" not in day3 and "10.0" not in day3


def test_shift_note_says_findings_are_not_recorded() -> None:
    ja = _shift_note(_shift_baby("ja", 1))[0]
    assert "日齢1。哺乳、排尿・排便、臍帯の所見は記録なし。" in ja
    assert "を観察。" not in ja


# ── H&P assessment / plan ──────────────────────────────────────────────


def _hp(lang: str, **workup):
    ctx = _ctx(lang)
    ctx.document_type = DocumentType.ADMISSION_HP
    ctx.code_status = "304253006"  # full resuscitation
    ctx.newborn_workup.update(
        {
            "birth": {"gestational_age_days": 270},
            "birth_weight_kg": 3.2,
            "has_vitamin_k": True,
            "has_ophthalmic": True,
            "has_aabr": True,
            "has_metabolic": True,
            "cchd_ru_spo2": 98,
            **workup,
        }
    )
    ctx.encounter["chief_complaint"] = "新生児 — 院内出生" if lang == "ja" else "Newborn - born in hospital"
    return ctx


def test_newborn_hp_ja_has_an_impression_and_a_plan_without_code_status() -> None:
    text, _ = build_assessment_and_plan(_GEN, _hp("ja"))
    assert "新生児 (在胎 38 週 4 日、出生体重 3.2 kg、Apgar 8点(1分)/10点(5分))。" in text, text
    for item in (
        "哺乳・排尿・排便・体重の経過を観察する。",
        "ビタミン K を予防投与する。",
        "眼科的予防投与を行う。",
        "新生児スクリーニング (聴覚 AABR、タンデム MS 代謝異常症、CCHD パルスオキシメトリ) を実施する。",
        "黄疸を経皮ビリルビン測定で経過観察する。",
    ):
        assert item in text, item
    assert "蘇生方針" not in text and "主訴" not in text, text


def test_newborn_hp_en_and_a_low_birth_weight_band() -> None:
    text, _ = build_assessment_and_plan(_GEN, _hp("en", birth_weight_kg=2.1))
    assert (
        "Newborn (gestational age 38w4d, birth weight 2.1 kg (low birth weight), Apgar 8 (1 min) / 10 (5 min))." in text
    )
    assert "Vitamin K prophylaxis." in text and "Newborn screening (hearing AABR, tandem-MS metabolic, CCHD" in text
    assert "resuscitat" not in text.lower() and not _CJK.search(text)
    extreme = build_assessment_and_plan(_GEN, _hp("en", birth_weight_kg=0.9))[0]
    assert "extremely low birth weight" in extreme
    assert "low birth weight" not in build_assessment_and_plan(_GEN, _hp("en", birth_weight_kg=2.5))[0]


def test_newborn_hp_states_only_what_the_record_holds() -> None:
    bare = _hp("ja", birth={}, birth_weight_kg=None, has_vitamin_k=False, has_ophthalmic=False, has_aabr=False)
    ctx = bare
    ctx.newborn_workup.update({"has_metabolic": False, "cchd_ru_spo2": None, "bilirubin_series": []})
    text, _ = build_assessment_and_plan(_GEN, ctx)
    assert "ビタミン K" not in text and "スクリーニング" not in text and "黄疸" not in text, text
    assert "新生児 (Apgar 8点(1分)/10点(5分))。" in text


def test_newborn_with_a_complication_keeps_the_code_status() -> None:
    ctx = _hp("ja")
    ctx.complications_events = [{"complication": "sepsis"}]
    assert "蘇生方針" in build_assessment_and_plan(_GEN, ctx)[0]
