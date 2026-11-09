"""Issue #2981: a potassium >= 6.0 mmol/L in hospital holds ACE inhibitors,
ARBs and potassium-sparing diuretics, places a hyperkalemia treatment order
set (calcium, insulin with dextrose, a potassium binder), and the progress
note plan says the drug is held instead of "Continue"."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import numpy as np
import pytest

from clinosim.codes.drugs import drug_classes, drug_ref
from clinosim.modules.drug_safety.hyperkalemia import (
    PotassiumHold,
    holds_for_hyperkalemia,
    hyperkalemia_rules,
    hyperkalemia_treatment_orders,
    potassium_hold_from_results,
)
from clinosim.simulator.medication_pipeline import _generate_mar
from clinosim.types.encounter import Order, OrderResult, OrderStatus, OrderType
from clinosim.types.patient import PatientProfile

pytestmark = pytest.mark.unit

_ADMIT = datetime(2026, 3, 1, 14, 0)


class _StubRoster:
    members: list = []

    def get_by_role(self, role: str, department: str | None = None) -> list:
        return []


def _order(order_id: str, drug: str) -> Order:
    return Order(
        order_id=order_id,
        encounter_id="ENC-2981",
        patient_id="POP-2981",
        order_type=OrderType.MEDICATION,
        display_name=drug,
        ordered_datetime=_ADMIT,
        status=OrderStatus.PLACED,
        route="PO",
        frequency_per_day=1,
    )


def _k(value: float, at: datetime, flag: str = "H") -> OrderResult:
    return OrderResult(result_datetime=at, lab_name="K", value=value, unit="mmol/L", flag=flag)


def _mar(orders: list[Order], day: int, hold: PotassiumHold | None) -> list:
    return _generate_mar(
        PatientProfile(patient_id="POP-2981"),
        orders,
        day,
        _ADMIT,
        roster=_StubRoster(),  # type: ignore[arg-type]
        rng=np.random.default_rng(0),
        potassium_hold=hold,
    )


def test_rules_name_the_held_classes_and_a_cited_threshold() -> None:
    rules = hyperkalemia_rules()
    assert rules.treat_threshold_mmol_l == 6.0
    assert {"acei", "arb", "diuretic.k_sparing"} <= set(rules.hold_classes)
    for drug in ("candesartan", "losartan", "enalapril", "lisinopril", "spironolactone"):
        assert holds_for_hyperkalemia(drug), drug
    for drug in ("amlodipine", "furosemide", "Calcium Gluconate 1 g IV"):
        assert not holds_for_hyperkalemia(drug), drug


def test_potassium_hold_starts_at_the_first_result_at_or_above_the_threshold() -> None:
    results = [_k(5.8, datetime(2026, 3, 2, 6, 40)), _k(6.5, datetime(2026, 3, 2, 7, 10))]
    hold = potassium_hold_from_results(results)
    assert hold is not None
    assert hold.since == datetime(2026, 3, 2, 7, 10)
    assert hold.value == 6.5
    assert PotassiumHold(since=hold.since, value=6.0).reason == "K 6.0 mmol/L"
    assert potassium_hold_from_results([_k(5.9, datetime(2026, 3, 2, 7, 0))]) is None
    # Other analytes never trigger.
    assert potassium_hold_from_results([OrderResult(lab_name="Na", value=160.0)]) is None


def test_candesartan_is_held_after_k_6_5() -> None:
    hold = potassium_hold_from_results([_k(6.5, datetime(2026, 3, 2, 6, 30))])
    candesartan, amlodipine = _order("ORD-CAN", "Candesartan 8mg"), _order("ORD-AML", "Amlodipine 5mg")
    day1 = _mar([candesartan, amlodipine], 1, hold)
    by_order = {m.order_id: m for m in day1}
    assert by_order["ORD-CAN"].status == "held"
    assert by_order["ORD-CAN"].actual_datetime is None
    assert "6.5" in (by_order["ORD-CAN"].hold_reason or "")
    assert by_order["ORD-AML"].status != "held"
    # Later days stay held; doses before the result are given as before.
    assert all(m.status == "held" for m in _mar([candesartan], 3, hold))
    day0 = _mar([candesartan], 0, hold)
    assert day0 and all(m.status != "held" for m in day0)


def test_no_hold_leaves_the_mar_unchanged() -> None:
    candesartan = _order("ORD-CAN", "Candesartan 8mg")
    assert _mar([candesartan], 1, None) == _generate_mar(
        PatientProfile(patient_id="POP-2981"),
        [candesartan],
        1,
        _ADMIT,
        roster=_StubRoster(),  # type: ignore[arg-type]
        rng=np.random.default_rng(0),
    )


@pytest.mark.parametrize("country", ["US", "JP"])
def test_a_hyperkalemia_treatment_order_is_placed(country: str) -> None:
    hold = potassium_hold_from_results([_k(6.5, datetime(2026, 3, 2, 6, 30))])
    assert hold is not None
    orders = hyperkalemia_treatment_orders(
        hold, patient_id="POP-2981", encounter_id="ENC-2981", country=country, day=1, ordered_by="DR-1"
    )
    classes = [set(drug_classes(o.display_name)) for o in orders]
    ids = {drug_ref(o.display_name) for o in orders}
    assert "calcium_gluconate" in ids  # membrane stabilisation
    assert "insulin_regular_human" in ids  # shift into cells
    assert any("potassium_binder" in c for c in classes)  # elimination
    for o in orders:
        assert o.order_type == OrderType.MEDICATION
        assert o.status == OrderStatus.PLACED
        assert o.single_dose
        assert o.ordered_datetime >= hold.since
        assert o.order_id.startswith("ORD-ENC-2981-HYPERK-D1-")
        assert "6.5" in o.clinical_intent and "6.5" in o.clinical_intent_ja
        assert o.dose_text_en and o.dose_text_ja
    # The treatment orders are given once, on the day they are ordered.
    mars = _mar(orders, 1, hold)
    assert {m.order_id for m in mars} == {o.order_id for o in orders}
    assert all(m.status in ("given", "refused") for m in mars)


def _ctx(lang: str, meds: list[dict]) -> SimpleNamespace:
    return SimpleNamespace(
        target_lang=lang, complications_occurred=[], lab_results=[], day_index=1, medications=meds, procedures=[]
    )


@pytest.mark.parametrize(
    ("lang", "held_head", "continue_head", "drug"),
    [("en", "Held:", "Continue current medications", "Candesartan"), ("ja", "休薬:", "薬物療法継続", "カンデサルタン")],
)
def test_progress_plan_says_the_drug_is_held(lang: str, held_head: str, continue_head: str, drug: str) -> None:
    from clinosim.modules.document.narrative.renderers._composers import compose_progress_plan_from_state

    meds = [
        {"drug_name": "Candesartan 8mg", "day": 1, "status": "held", "hold_reason": "K 6.5 mmol/L"},
        {"drug_name": "Calcium Gluconate 1 g IV", "day": 1, "status": "given"},
    ]
    plan = compose_progress_plan_from_state(_ctx(lang, meds))
    held_part = plan[plan.index(held_head) :]
    assert drug in held_part and "K 6.5 mmol/L" in held_part
    continue_part = plan[: plan.index(held_head)]
    assert continue_head in continue_part
    assert drug not in continue_part


def test_an_authored_japanese_plan_also_names_the_held_drug() -> None:
    """The JA progress note prefers the disease's authored daily plan, which
    lists no drugs; the held drug is added to it."""
    from unittest.mock import patch

    from clinosim.modules.document.narrative.registry import load_document_type_specs
    from clinosim.modules.document.narrative.renderers.progress_note import render_progress_note
    from clinosim.modules.document.narrative.template_generator import TemplateNarrativeGenerator
    from clinosim.types.document import DocumentType

    spec = load_document_type_specs()[DocumentType.PROGRESS_NOTE]
    gen = TemplateNarrativeGenerator()
    meds = [{"drug_name": "Candesartan 8mg", "day": 1, "status": "held", "hold_reason": "K 6.5 mmol/L"}]
    traj = {"subjective": "症状軽快", "objective": "", "assessment": "改善傾向", "plan": "補液継続"}
    with patch.object(gen, "_resolve_daily_trajectory_with_source", return_value=(traj, "")):
        ctx = _ctx("ja", meds)
        for attr in ("clinical_course_archetype", "encounter", "patient", "disease_protocol", "severity"):
            setattr(ctx, attr, None)
        ctx.vitals, ctx.diagnoses, ctx.allergies, ctx.los_days = [], [], [], 5
        out = render_progress_note(gen, ctx, spec)
    assert "補液継続。休薬: カンデサルタン" in out.raw_text + "".join(out.sections.values())


@pytest.mark.parametrize("country", ["US", "JP"])
def test_a_persisting_hyperkalemia_repeats_only_the_binder(country: str) -> None:
    hold = potassium_hold_from_results([_k(6.3, datetime(2026, 3, 3, 6, 30))])
    assert hold is not None
    orders = hyperkalemia_treatment_orders(
        hold, patient_id="POP-2981", encounter_id="ENC-2981", country=country, day=2, continuing=True
    )
    assert orders and all("potassium_binder" in drug_classes(o.display_name) for o in orders)
