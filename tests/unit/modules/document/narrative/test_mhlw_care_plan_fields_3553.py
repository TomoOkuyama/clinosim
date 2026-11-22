"""Issue #3553: the MHLW nutrition care plan and admission care plan derive
their special-nutrition, goal, dysphagia, dietitian and final-evaluation
fields from the record instead of printing one fixed phrase."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from typing import Any

from clinosim.modules.document.narrative.template_generator import TemplateNarrativeGenerator
from clinosim.types.document import DocumentType, NarrativeContext
from tests.unit.modules.document.narrative.test_template_generator_admission_care_plan import (
    _make_spec as _acp_spec,
)
from tests.unit.modules.document.narrative.test_template_generator_nutrition_care_plan import (
    _make_ctx as _ncp_ctx,
)
from tests.unit.modules.document.narrative.test_template_generator_nutrition_care_plan import (
    _make_patient,
    _make_spec,
)

_ADM = datetime(2026, 7, 1, 10, 0)


def _ctx(
    *,
    bmi: float = 22.5,
    conditions: list[str] | None = None,
    diet: str | None = None,
    diagnoses: list[str] | None = None,
    died: bool = False,
    roster: dict[str, dict] | None = None,
    lang: str = "ja",
) -> NarrativeContext:
    patient = _make_patient(bmi=bmi)
    patient.chronic_conditions = [SimpleNamespace(code=c) for c in conditions or []]  # type: ignore[misc]
    ctx = _ncp_ctx(patient=patient, target_lang=lang, locale="jp" if lang == "ja" else "us")
    ctx.authored_datetime = _ADM.replace(hour=18)
    if diet:
        ctx.orders = [
            SimpleNamespace(order_type="diet", display_name=diet, ordered_datetime=_ADM.replace(hour=17).isoformat())
        ]
    ctx.diagnoses = [SimpleNamespace(admission_diagnosis_code=c, discharge_diagnosis_code="") for c in diagnoses or []]
    if died:
        ctx.encounter.discharge_disposition = "exp"
    ctx.roster_map = roster or {}
    return ctx


def _ncp(ctx: NarrativeContext) -> dict[str, str]:
    return TemplateNarrativeGenerator().generate(ctx, _make_spec()).sections


def _acp(ctx: NarrativeContext) -> str:
    ctx.document_type = DocumentType.ADMISSION_CARE_PLAN
    return TemplateNarrativeGenerator().generate(ctx, _acp_spec()).sections["special_nutrition_management"]


def test_special_nutrition_is_yes_for_a_high_risk_patient_in_both_forms() -> None:
    ctx = _ctx(bmi=15.0, diet="regular_diet")
    assert "有" in _acp(ctx)
    assert "低栄養リスク高" in _acp(ctx)
    assert "改善" in _ncp(ctx)["nutrition_goals"]
    assert "維持" not in _ncp(ctx)["nutrition_goals"]


def test_special_nutrition_is_yes_for_diabetes_and_ckd_and_lists_them() -> None:
    ctx = _ctx(conditions=["E11.9", "N18.3"], diet="regular_diet")
    text = _acp(ctx)
    assert "有" in text and "糖尿病" in text and "CKD" in text
    assert "糖尿病" in _ncp(ctx)["nutrition_goals"]


def test_special_nutrition_is_no_for_a_low_risk_patient() -> None:
    ctx = _ctx(diet="regular_diet")
    assert _acp(ctx) == "特別な栄養管理の必要性：無"
    assert "現在の栄養状態を維持" in _ncp(ctx)["nutrition_goals"]


def test_special_nutrition_is_yes_when_nil_by_mouth_en() -> None:
    assert "Yes" in _acp(_ctx(diet="NPO", lang="en"))


def test_npo_plan_has_no_energy_value_and_states_no_nutrition_order() -> None:
    supply = _ncp(_ctx(diet="NPO"))["nutrition_supply"]
    assert "kcal" not in supply
    assert "絶食中のため経口摂取なし" in supply
    assert "記録なし" in supply


def test_oral_plan_keeps_the_energy_value() -> None:
    assert "kcal" in _ncp(_ctx(diet="regular_diet"))["nutrition_supply"]


def test_dysphagia_not_asserted_none_after_a_stroke_or_when_nil_by_mouth() -> None:
    assert "未評価" in _ncp(_ctx(diet="regular_diet", diagnoses=["I63.9"]))["dysphagia_diet"]
    assert "未評価" in _ncp(_ctx(diet="NPO"))["dysphagia_diet"]
    assert "なし" in _ncp(_ctx(diet="regular_diet"))["dysphagia_diet"]


def test_dietitian_is_named_from_the_roster_else_not_assigned() -> None:
    roster = {"RD-001": {"staff_id": "RD-001", "name": "山田 花子", "role": "dietitian"}}
    assert "山田 花子" in _ncp(_ctx(roster=roster))["dietitian"]
    text = _ncp(_ctx())["dietitian"]
    assert "未定" in text and "担当なし" not in text


def test_discharge_evaluation_for_a_death_is_not_a_forward_looking_placeholder() -> None:
    died = _ncp(_ctx(died=True))["discharge_evaluation"]
    assert "評価予定" not in died and "死亡" in died
    assert "評価予定" in _ncp(_ctx())["discharge_evaluation"]


def test_sections_are_english_without_japanese_in_us_locale() -> None:
    out: dict[str, Any] = _ncp(_ctx(bmi=15.0, diet="NPO", died=True, lang="en"))
    for key in ("nutrition_goals", "dysphagia_diet", "dietitian", "discharge_evaluation", "nutrition_supply"):
        assert all(ord(ch) < 0x3000 for ch in out[key]), (key, out[key])
