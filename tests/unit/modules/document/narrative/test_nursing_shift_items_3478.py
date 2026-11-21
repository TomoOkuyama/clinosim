"""Nursing shift note items derived from the shift's vitals (Issue #3478)."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from clinosim.locale.i18n import t
from clinosim.modules.document.narrative._nursing_shift_items import ITEM_FUNCTIONS, nursing_shift_items_config
from clinosim.modules.document.narrative.renderers.nursing_shift_note import render_nursing_shift_note
from clinosim.modules.document.narrative.semantic_check import _ALLOWED_FACT_PREFIXES
from clinosim.modules.observation.nursing import news2_urgent_response_threshold

pytestmark = pytest.mark.unit

_ADM = "2026-08-31T09:54:00"
_DAY = "2026-08-31"


def _ctx(lang: str, vitals: list[dict], meds: list[dict] | None = None, **kw) -> SimpleNamespace:
    base = {
        "target_lang": lang,
        "locale": "jp" if lang == "ja" else "us",
        "authored_datetime": datetime(2026, 8, 31, 17, 0),
        "day_index": 0,
        "shift": "day",
        "encounter": {"admission_datetime": _ADM, "primary_nurse_id": ""},
        "roster_map": {},
        "vitals": vitals,
        "medications": meds or [],
        "nursing_risk_assessments": [],
        "patient": {"date_of_birth": "1950-01-01"},
        "disease_protocol": None,
        "author_practitioner_id": "",
    }
    base.update(kw)
    return SimpleNamespace(**base)


def _v(hhmm: str, **kw) -> dict:
    return {"timestamp": f"{_DAY}T{hhmm}:00", **kw}


def _note(lang: str, vitals: list[dict], meds: list[dict] | None = None, **kw):
    out = render_nursing_shift_note(_ctx(lang, vitals, meds, **kw), SimpleNamespace())
    return out.raw_text, out.facts_used


def _mar(hhmm: str, name: str) -> dict:
    return {"drug_name": name, "status": "given", "actual_datetime": f"{_DAY}T{hhmm}:00"}


def test_registry_matches_functions_and_phrases() -> None:
    ids = [i.id for i in nursing_shift_items_config().items]
    assert set(ids) == set(ITEM_FUNCTIONS)
    for item in nursing_shift_items_config().items:
        assert item.fact.startswith(_ALLOWED_FACT_PREFIXES)
    # Every phrase of every item exists in ja and en.
    for key in (
        "pain.none",
        "pain.single",
        "pain.range",
        "fever.observed",
        "fever.improved",
        "fever.given",
        "fever.lower",
        "fever.persisting",
        "desaturation.on_oxygen",
        "desaturation.oxygen_started",
        "desaturation.observed",
        "consciousness.new",
        "consciousness.persistent",
        "consciousness.transient",
        "news2.urgent",
        "not_given.act_oral",
        "not_given.act_other",
        "not_given.held",
        "not_given.held_plain",
        "not_given.refused",
        "not_given.refused_reason",
        "not_given.unavailable",
        "hold_reason.sbp",
        "hold_reason.hr",
    ):
        for lang in ("ja", "en"):
            assert t(f"nursing_shift_items.{key}", lang) != f"nursing_shift_items.{key}"


def test_fever_with_antipyretic_and_recheck_ja() -> None:
    vitals = [_v("10:00", temperature_celsius=38.4), _v("14:00", temperature_celsius=37.6)]
    text, facts = _note("ja", vitals, [_mar("11:00", "Acetaminophen 500mg")])
    assert "38.4°Cの発熱あり、アセトアミノフェン投与後 37.6°Cに解熱傾向。" in text
    assert "ctx.vitals.shift.fever" in facts


def test_fever_with_antipyretic_en() -> None:
    vitals = [_v("10:00", temperature_celsius=38.4), _v("14:00", temperature_celsius=37.6)]
    text, _ = _note("en", vitals, [_mar("11:00", "Acetaminophen 500mg")])
    assert "Fever 38.4°C; Acetaminophen given, temperature down to 37.6°C afterwards." in text


def test_fever_without_antipyretic_is_observation() -> None:
    text, _ = _note("ja", [_v("10:00", temperature_celsius=38.2)])
    assert "38.2°Cの発熱あり、経過観察。" in text


def test_no_fever_item_below_threshold() -> None:
    text, facts = _note("ja", [_v("10:00", temperature_celsius=37.9)])
    assert "発熱あり" not in text
    assert "ctx.vitals.shift.fever" not in facts


def test_antipyretic_after_authored_time_is_not_quoted() -> None:
    # The dose at 18:00 is after the note's authored time (17:00).
    text, _ = _note("ja", [_v("10:00", temperature_celsius=38.2)], [_mar("18:00", "Acetaminophen 500mg")])
    assert "アセトアミノフェン投与後" not in text and "38.2°Cの発熱あり、経過観察。" in text


def test_pain_score_and_site() -> None:
    vitals = [_v("10:00", pain_score=6), _v("15:00", pain_score=3)]
    ja, _ = _note("ja", vitals)
    assert "NRS 最大 6、最終 3" in ja
    en, facts = _note("en", [_v("10:00", pain_score=4)])
    assert "Pain reported, NRS 4." in en  # generic label without a named pain source
    assert "ctx.vitals.shift.pain" in facts


def test_pain_zero_and_absent() -> None:
    zero, _ = _note("ja", [_v("10:00", pain_score=0)])
    assert "疼痛の訴えなし (NRS 0)。" in zero
    none, facts = _note("ja", [_v("10:00", heart_rate=80)])
    assert "NRS" not in none and "ctx.vitals.shift.pain" not in facts


def test_desaturation_with_oxygen_response() -> None:
    vitals = [
        _v("09:30", spo2=89, on_supplemental_oxygen=False),
        _v(
            "12:00",
            spo2=95,
            on_supplemental_oxygen=True,
            oxygen_delivery_device="nasal_cannula",
            oxygen_flow_rate_lpm=2,
        ),
    ]
    ja, facts = _note("ja", vitals)
    assert "09:30 SpO2 89%に低下、" in ja and "投与後 SpO2 95%" in ja
    assert "ctx.vitals.shift.desaturation" in facts
    obs, _ = _note("en", [_v("10:00", spo2=90, on_supplemental_oxygen=False)])
    assert "no oxygen given, observation continued." in obs


def test_desaturation_uses_patient_floor() -> None:
    # SpO2 90 is not low for a COPD patient (floor 88).
    protocol = SimpleNamespace(disease_id="copd_exacerbation")
    text, facts = _note("ja", [_v("10:00", spo2=90)], disease_protocol=protocol)
    assert "に低下" not in text and "ctx.vitals.shift.desaturation" not in facts


def test_consciousness_new_persistent_transient() -> None:
    new, _ = _note("ja", [_v("10:00", consciousness_level="V")])
    assert "意識レベル低下あり (AVPU V)" in new
    prior = [_v("07:00", consciousness_level="V"), _v("10:00", consciousness_level="V")]
    prior[0]["timestamp"] = "2026-08-31T05:00:00"
    persistent, _ = _note("en", prior)
    assert "remains decreased (AVPU V)" in persistent
    transient, _ = _note("ja", [_v("10:00", consciousness_level="P"), _v("14:00", consciousness_level="A")])
    assert "一過性の意識レベル低下 (AVPU P)" in transient


def test_news2_urgent_latest_reading() -> None:
    thr = news2_urgent_response_threshold()
    text, facts = _note("ja", [_v("10:00", news2_score=thr + 1)])
    assert f"NEWS2 {thr + 1}、緊急対応基準" in text and "ctx.vitals.shift.news2" in facts
    low, _ = _note("ja", [_v("10:00", news2_score=1)])
    assert "緊急対応基準" not in low


def test_default_line_only_when_nothing_fired() -> None:
    quiet, _ = _note("ja", [_v("10:00", heart_rate=80)])
    assert "特記事項なし" in quiet
    busy, _ = _note("ja", [_v("10:00", temperature_celsius=38.5)])
    assert "特記事項なし" not in busy


def test_vitals_nursing_note_text_is_not_printed() -> None:
    text, _ = _note("ja", [_v("10:00", temperature_celsius=38.5, nursing_note="febrile recheck after 30 min")])
    assert "febrile recheck" not in text


def _row(hhmm: str, name: str, status: str, **kw) -> dict:
    return {
        "drug_name": name,
        "status": status,
        "scheduled_datetime": f"{_DAY}T{hhmm}:00",
        "actual_datetime": None,
        "route": "PO",
        **kw,
    }


def test_held_dose_with_reason_ja_and_en() -> None:
    meds = [_row("12:00", "Amlodipine 5mg", "held", hold_reason="SBP < 90")]
    ja, facts = _note("ja", [], meds)
    assert "アムロジピン内服は血圧低値 (SBP 90未満)のため保留。" in ja
    assert "ctx.medications.shift.not_given" in facts
    en, _ = _note("en", [], meds)
    assert "Amlodipine oral dose held: low blood pressure (SBP below 90)." in en


def test_refused_dose_ja_and_en_once_per_drug() -> None:
    meds = [_row("12:00", "Amlodipine 5mg", "refused"), _row("13:00", "Amlodipine 5mg", "refused")]
    ja, _ = _note("ja", [], meds)
    assert ja.count("アムロジピン内服を拒否。") == 1
    en, _ = _note("en", [], meds)
    assert en.count("Patient refused Amlodipine oral dose.") == 1


def test_refusal_reason_and_unlisted_hold_reason() -> None:
    meds = [
        _row("12:00", "Amlodipine 5mg", "refused", refusal_reason="nausea"),
        _row("13:00", "Metformin 500mg", "held", hold_reason="K 6.1 mmol/L", route="IV"),
    ]
    ja, _ = _note("ja", [], meds)
    assert "アムロジピン内服を拒否 (nausea)。" in ja
    assert "K 6.1 mmol/L のため" not in ja and "メトホルミン投与はK 6.1 mmol/Lのため保留。" in ja


def test_not_given_rows_outside_shift_or_after_authored_are_not_stated() -> None:
    meds = [
        _row("07:00", "Amlodipine 5mg", "held", hold_reason="SBP < 90"),  # before the day shift
        _row("18:00", "Amlodipine 5mg", "refused"),  # after authored 17:00
    ]
    ja, facts = _note("ja", [], meds)
    assert "保留" not in ja and "拒否" not in ja
    assert "ctx.medications.shift.not_given" not in facts


def test_not_given_drug_is_not_in_given_line() -> None:
    meds = [_row("12:00", "Amlodipine 5mg", "held", hold_reason="SBP < 90"), _mar("13:00", "Loxoprofen 60mg")]
    ja, _ = _note("ja", [], meds)
    given = next(line for line in ja.split("\n") if line.startswith(t("nursing_shift.meds_head", "ja")))
    assert "アムロジピン" not in given and "ロキソプロフェン" in given
