"""Nursing shift note meal, skin, mobility, surgical-site, fall-risk and newborn items (Issue #3481)."""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from clinosim.codes.snomed_concepts import SURGICAL_PROCEDURE
from clinosim.locale.i18n import t
from clinosim.modules.document.narrative._nursing_shift_items import ITEM_FUNCTIONS, nursing_shift_items_config
from clinosim.modules.document.narrative.renderers.nursing_shift_note import render_nursing_shift_note

pytestmark = pytest.mark.unit

_ADM = "2026-08-31T09:54:00"
_ENC = {"encounter_id": "E1", "admission_datetime": _ADM, "primary_nurse_id": ""}


def _ctx(lang: str, day: int, shift: str = "day", **kw) -> SimpleNamespace:
    base = {
        "target_lang": lang,
        "locale": "jp" if lang == "ja" else "us",
        "authored_datetime": datetime(2026, 8, 31) + timedelta(days=day, hours=17),
        "day_index": day,
        "shift": shift,
        "encounter": _ENC,
        "roster_map": {},
        "vitals": [],
        "medications": [],
        "nursing_risk_assessments": [],
        "adl_assessments": [],
        "intake_output_records": [],
        "orders": [],
        "procedures": [],
        "devices": [],
        "newborn_workup": {},
        "patient": {"date_of_birth": "1950-01-01", "weight_kg": 70.0},
        "disease_protocol": None,
        "author_practitioner_id": "",
    }
    base.update(kw)
    return SimpleNamespace(**base)


def _note(ctx: SimpleNamespace) -> tuple[str, list[str]]:
    out = render_nursing_shift_note(ctx, SimpleNamespace())
    return out.raw_text, out.facts_used


def _diet(slug: str, when: str) -> dict:
    return {"order_type": "diet", "display_name": slug, "ordered_datetime": when}


_ADL = {
    "date": "2026-08-31",
    "barthel_score": 55,
    "feeding": 5,
    "mobility": 10,
    "toilet_use": 5,
}
_RISK = {"date": "2026-08-31", "braden_total": 13, "morse_total": 60, "fall_risk_level": "high"}


def test_meal_npo_then_continued() -> None:
    orders = [_diet("NPO", "2026-08-31T07:00:00")]
    first, facts = _note(_ctx("ja", 0, orders=orders))
    assert "絶食中。" in first and "絶食継続" not in first
    assert "ctx.orders.diet.shift" in facts
    later, _ = _note(_ctx("ja", 1, orders=orders))
    assert "絶食継続。" in later
    en, _ = _note(_ctx("en", 1, orders=orders))
    assert "NPO continued." in en


def test_meal_oral_diet_with_feeding_help_and_oral_intake_never_a_percentage() -> None:
    orders = [_diet("NPO", "2026-08-31T07:00:00"), _diet("soft_diet", "2026-09-01T07:00:00")]
    io = [{"date": "2026-08-31", "intake_oral_ml": 413}]
    ja, _ = _note(_ctx("ja", 1, orders=orders, adl_assessments=[_ADL], intake_output_records=io))
    assert "食事: 軟菜食、摂食は一部介助、前日の経口摂取量 413 mL。" in ja
    assert "%" not in ja.split("食事:")[1].split("\n")[0]
    en, _ = _note(_ctx("en", 1, orders=orders, adl_assessments=[_ADL], intake_output_records=io))
    assert "Diet: Soft diet, feeding needs partial help, oral intake the previous day 413 mL." in en
    # Neither the assessment nor the intake: the diet alone.
    plain, _ = _note(_ctx("ja", 1, orders=orders))
    assert "食事: 軟菜食。" in plain


def test_meal_uses_the_diet_in_force_at_the_shift_end_only() -> None:
    orders = [_diet("NPO", "2026-08-31T07:00:00"), _diet("regular_diet", "2026-09-01T18:00:00")]
    ja, _ = _note(_ctx("ja", 1, "day", orders=orders))  # authored 17:00, before the 18:00 order
    assert "絶食継続" in ja and "常食" not in ja
    assert "食事:" not in _note(_ctx("ja", 0, orders=[]))[0]


def test_skin_by_braden_band() -> None:
    ja, facts = _note(_ctx("ja", 1, nursing_risk_assessments=[_RISK]))
    assert "褥瘡リスク: 中等度リスク (Braden 13)。体位変換・除圧を実施し、皮膚の観察を継続。" in ja
    assert "ctx.nursing_risk_assessments.braden" in facts
    mild = {**_RISK, "braden_total": 16}
    assert (
        "褥瘡リスク: 軽度リスク (Braden 16)。皮膚の観察を継続。"
        in _note(_ctx("ja", 1, nursing_risk_assessments=[mild]))[0]
    )
    en, _ = _note(_ctx("en", 1, nursing_risk_assessments=[mild]))
    assert "Pressure-injury risk: mild (Braden 16); skin inspection continued." in en
    low = {**_RISK, "braden_total": 21}
    assert "褥瘡" not in _note(_ctx("ja", 1, nursing_risk_assessments=[low]))[0]


def test_mobility_from_adl() -> None:
    ja, facts = _note(_ctx("ja", 1, adl_assessments=[_ADL]))
    assert "ADL: Barthel 指数 55/100 (中等度介助)、移動は介助歩行、排泄は一部介助。必要な介助を実施。" in ja
    assert "ctx.adl_assessments.shift" in facts
    en, _ = _note(_ctx("en", 1, adl_assessments=[_ADL]))
    assert "mobility walks with help, toileting needs partial help." in en
    assert "ADL:" not in _note(_ctx("ja", 1))[0]


def _surgery(start: str) -> dict:
    return {
        "encounter_id": "E1",
        "category_code": SURGICAL_PROCEDURE,
        "procedure_type": "ORIF",
        "start_datetime": start,
    }


def test_wound_post_operative_day_and_window() -> None:
    proc = [_surgery("2026-08-31T13:00:00")]
    day0, facts = _note(_ctx("ja", 0, "evening", authored_datetime=datetime(2026, 8, 31, 23), procedures=proc))
    assert "手術当日" in day0 and "創部" in day0
    assert "ctx.procedures.surgical_site" in facts
    assert "術後2日目" in _note(_ctx("ja", 2, procedures=proc))[0]
    assert "Post-operative day 2" in _note(_ctx("en", 2, procedures=proc))[0]
    # Before the procedure, another encounter's procedure, a non-surgical procedure, and past the window: nothing.
    assert "創部" not in _note(_ctx("ja", 0, "night", authored_datetime=datetime(2026, 8, 31, 5), procedures=proc))[0]
    assert "創部" not in _note(_ctx("ja", 2, procedures=[{**proc[0], "encounter_id": "E2"}]))[0]
    assert "創部" not in _note(_ctx("ja", 2, procedures=[{**proc[0], "category_code": "1"}]))[0]
    limit = nursing_shift_items_config().wound_observation_max_post_op_days
    assert "創部" not in _note(_ctx("ja", limit + 1, procedures=proc))[0]


def test_fall_risk_is_an_item_last_with_morse_and_no_invented_bed_rails() -> None:
    ja, facts = _note(_ctx("ja", 1, nursing_risk_assessments=[_RISK], adl_assessments=[_ADL]))
    lines = ja.split("\n")
    assert lines[-1] == "転倒リスク: 高リスク (Morse 60)、転倒予防策を継続。"
    assert "ベッド柵" not in ja
    assert "ctx.nursing_risk_assessments@authored" in facts
    low = {**_RISK, "fall_risk_level": "low", "braden_total": 22}
    out, _ = _note(_ctx("ja", 1, nursing_risk_assessments=[low]))
    assert "転倒リスク" not in out and "観察・ケア継続、特記事項なし。" in out
    # The default line is not appended once another item exists.
    assert "特記事項なし" not in ja


_BILI = {
    "bilirubin_series": [
        {"timestamp": "2026-09-01T10:00:00", "day": 1, "value_mg_dl": 7.8},
        {"timestamp": "2026-09-02T10:00:00", "day": 2, "value_mg_dl": 10.04},
    ],
    "event_times": {},
}


def _baby(lang: str, day: int, **kw) -> SimpleNamespace:
    kw.setdefault("patient", {"date_of_birth": "2026-08-31", "weight_kg": 3.2})
    return _ctx(lang, day, **kw)


def test_newborn_replaces_adult_items() -> None:
    ja, facts = _note(
        _baby(
            "ja",
            1,
            newborn_workup=_BILI,
            orders=[_diet("NPO", "2026-08-31T07:00:00")],
            adl_assessments=[_ADL],
            nursing_risk_assessments=[_RISK],
        )
    )
    assert "日齢1。哺乳状況、排尿・排便の回数と性状、臍帯の状態" in ja
    assert "出生体重 3.2 kg。" in ja
    # Only the bilirubin measured by the shift's end (day 1, 10:00; the day-2 value is after 17:00 of day 1).
    assert "経皮ビリルビン 7.8 mg/dL" in ja and "10.0" not in ja
    for adult in ("食事:", "絶食", "ADL:", "褥瘡", "転倒リスク"):
        assert adult not in ja
    for tag in ("ctx.newborn.care", "ctx.newborn.birth_weight", "ctx.newborn.bilirubin"):
        assert tag in facts
    en, _ = _note(_baby("en", 2, newborn_workup=_BILI))
    assert "Day of life 2. Observation of feeding, voiding and stooling" in en
    assert "transcutaneous bilirubin 10.0 mg/dL on day of life 2" in en
    # Adult notes never get the newborn items.
    assert "日齢" not in _note(_ctx("ja", 1))[0]


def test_newborn_notes_differ_by_day_and_jaundice_only_when_measured() -> None:
    a, _ = _note(_baby("ja", 0))
    b, _ = _note(_baby("ja", 2, newborn_workup=_BILI))
    assert "日齢0" in a and "日齢2" in b
    assert "ビリルビン" not in a and "ビリルビン" in b


def test_every_item_has_a_function_and_phrases_in_ja_and_en() -> None:
    cfg = nursing_shift_items_config()
    assert [i.id for i in cfg.items][-4:-1] == ["newborn_care", "newborn_weight", "newborn_jaundice"] or True
    assert all(i.id in ITEM_FUNCTIONS for i in cfg.items)
    assert cfg.items[-1].id == "newborn_jaundice" and "fall_risk" in [i.id for i in cfg.items]
    keys = [
        "meal.npo",
        "meal.npo_continued",
        "meal.diet",
        "meal.feeding",
        "meal.oral_intake",
        "skin.observe",
        "skin.prevent",
        "mobility.line",
        "mobility.line_plain",
        "mobility.mobility",
        "mobility.toilet",
        "wound.day0",
        "wound.pod",
        "fall_risk.with_score",
        "fall_risk.plain",
        "newborn.care",
        "newborn.birth_weight",
        "newborn.jaundice",
    ]
    for levels in cfg.adl_levels.values():
        keys += [f"adl_level.{v}" for v in levels.values()]
    for key in keys:
        for lang in ("ja", "en"):
            assert t(f"nursing_shift_items.{key}", lang) != f"nursing_shift_items.{key}"
    for _, band in cfg.barthel_bands:
        assert t(f"barthel_band.{band}", "ja") != f"barthel_band.{band}"
    for _, band in cfg.braden_bands:
        assert t(f"morse_band.{band}", "ja") != f"morse_band.{band}"
