"""Issue #3411: a progress note states each held drug once with one reason,
words a route switch as a change, keeps the reason out of an ungrammatical
"...)のため", and carries a hold across the days until it is lifted."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from clinosim.locale.loader import hold_reason_change, load_medication_hold_reasons
from clinosim.modules.document.narrative._medication_plan import note_medications
from clinosim.modules.document.narrative._safety_skips import progress_note_safety_skips
from clinosim.modules.document.narrative._template_helpers import _render_safety_skips_line
from clinosim.modules.document.narrative.renderers._composers import compose_progress_plan_from_state

_HF_REASON = "Acute HF exacerbation — oral diuretic replaced by IV furosemide"
_AKI_REASON = "AKI: RAAS blockade held per KDIGO 2012 § 3.5.2"


def _skip(drug: str, ja: str, reason: str, reason_ja: str, rule_id: str, key: str = "") -> dict:
    return {
        "considered": drug,
        "considered_ja": ja,
        "avoided_due_to": reason,
        "avoided_due_to_ja": reason_ja,
        "substituted_with": None,
        "event_type": "hold",
        "rule_id": rule_id,
        "hold_reason_key": key,
        "conflict_kind": None,
    }


def _furosemide_pair() -> list[dict]:
    return [
        _skip(
            "Furosemide",
            "フロセミド",
            "acute HF exacerbation (oral diuretic held, IV furosemide substituted)",
            "急性心不全増悪 (内服利尿薬を静注フロセミドに変更)",
            "medication-hold:heart_failure_exacerbation",
            _HF_REASON,
        ),
        _skip(
            "Furosemide",
            "フロセミド",
            "heart failure exacerbation discharge protocol",
            "心不全増悪の退院プロトコル",
            "discharge-medication-hold",
        ),
    ]


def _render(skips: list[dict], lang: str, held_refs: frozenset[str] = frozenset()) -> str:
    return _render_safety_skips_line(progress_note_safety_skips(skips, held_refs), lang)


@pytest.mark.parametrize("lang", ["en", "ja"])
def test_discharge_stage_hold_is_not_a_daily_plan_line(lang: str) -> None:
    text = _render(_furosemide_pair(), lang)
    assert text.count("\n") == 0
    assert "退院プロトコル" not in text and "discharge protocol" not in text


def test_route_switch_is_a_change_not_a_hold() -> None:
    ja = _render(_furosemide_pair(), "ja")
    assert "内服 → 静注に変更" in ja and "保留" not in ja and "のため" not in ja
    en = _render(_furosemide_pair(), "en")
    assert "switched from oral to IV" in en and "held" not in en


def test_hold_reason_is_parenthesised_without_a_connective() -> None:
    skip = _skip("Candesartan", "カンデサルタン", "x", "急性腎障害 (ARB — ACE 阻害薬と同じ)", "medication-hold:aki")
    text = _render([skip], "ja")
    assert text == "・カンデサルタン：今回入院中は保留（急性腎障害 (ARB — ACE 阻害薬と同じ)）。"
    assert ")のため" not in text


def test_a_drug_held_by_two_in_stay_events_is_one_line() -> None:
    first = _skip("Candesartan", "カンデサルタン", "AKI one", "急性腎障害A", "medication-hold:aki")
    second = _skip("Candesartan", "カンデサルタン", "AKI two", "急性腎障害B", "medication-hold:other")
    text = _render([first, second], "ja")
    assert text.count("カンデサルタン") == 1 and "急性腎障害A" in text and "急性腎障害B" not in text


def test_an_event_logged_twice_is_stated_once() -> None:
    avoid = dict(
        _skip("Potassium chloride", "塩化カリウム", "Candesartan", "カンデサルタン", "k-plus-arb"), event_type="avoid"
    )
    assert _render([avoid, dict(avoid)], "ja").count("塩化カリウム") == 1


def test_a_drug_the_mar_holds_today_is_not_repeated_by_the_skip_line() -> None:
    skip = _skip("Candesartan", "カンデサルタン", "AKI", "急性腎障害", "medication-hold:aki")
    assert _render([skip], "ja", frozenset({"candesartan"})) == ""
    assert _render([skip], "ja", frozenset({"furosemide"})) != ""


def _ctx(lang: str, meds: list[dict], day: int) -> SimpleNamespace:
    return SimpleNamespace(
        target_lang=lang,
        day_index=day,
        medications=meds,
        procedures=[],
        orders=[],
        encounter=None,
        authored_datetime=None,
    )


def _dose(day: int, status: str = "given") -> dict:
    row = {"drug_name": "Candesartan", "day": day, "status": status}
    if status == "held":
        row["hold_reason"] = _AKI_REASON
    return row


@pytest.mark.parametrize(
    ("lang", "resumed", "held_word"), [("en", "Resumed: Candesartan", "Held:"), ("ja", "再開: カンデサルタン", "休薬:")]
)
def test_a_lifted_hold_is_stated_as_a_resume(lang: str, resumed: str, held_word: str) -> None:
    meds = [_dose(0), _dose(1, "held"), _dose(2)]
    plan = compose_progress_plan_from_state(_ctx(lang, meds, 2))
    assert resumed in plan and "Continue" not in plan and "継続" not in plan and held_word not in plan
    assert resumed not in compose_progress_plan_from_state(_ctx(lang, meds, 1))


@pytest.mark.parametrize(("lang", "held_word"), [("en", "Held: Candesartan"), ("ja", "休薬: カンデサルタン")])
def test_a_hold_persists_until_a_dose_is_given(lang: str, held_word: str) -> None:
    meds = [_dose(0), _dose(1, "held"), _dose(3)]
    plan = compose_progress_plan_from_state(_ctx(lang, meds, 2))
    assert held_word in plan and "Stopped" not in plan and "中止" not in plan
    meds_now = note_medications(_ctx(lang, meds, 2))
    assert meds_now.stopped == [] and len(meds_now.held) == 1 and meds_now.resumed == []


def test_hold_reason_table_change_entries_are_complete() -> None:
    changes = {k: hold_reason_change(k, "en") for k in load_medication_hold_reasons() if hold_reason_change(k, "en")}
    assert _HF_REASON in changes
    for key in changes:
        for lang in ("en", "ja"):
            assert hold_reason_change(key, lang), (key, lang)
            assert hold_reason_change(key, lang, reason_text=True), (key, lang)
