"""Issue #3233: antihypertensives, diuretics, nitrates and beta-blockers are
held while a vasopressor or inotrope infusion runs, and the vital-sign hold
parameters (SBP < 90, HR < 50) are judged on the latest vital signs recorded
in the stay before each dose, not on the pre-admission baseline."""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

import numpy as np
import pytest

from clinosim.locale.loader import hold_reason_display
from clinosim.simulator.medication_pipeline import (
    _generate_mar,
    apply_vital_holds,
    vasoactive_hold_reason,
    vasoactive_hold_rules,
    vasoactive_infusions,
)
from clinosim.types.encounter import MedicationAdministration, Order, OrderStatus, OrderType, VitalSignRecord
from clinosim.types.patient import BaselineVitals, PatientProfile

pytestmark = pytest.mark.unit

_ADMIT = datetime(2026, 3, 1, 14, 0)
_NE_START = datetime(2026, 3, 2, 10, 0)


class _StubRoster:
    members: list = []

    def get_by_role(self, role: str, department: str | None = None) -> list:
        return []


def _order(order_id: str, drug: str, *, route: str = "PO", at: datetime = _ADMIT, **kw) -> Order:
    return Order(
        order_id=order_id,
        encounter_id="ENC-3233",
        patient_id="POP-3233",
        order_type=OrderType.MEDICATION,
        display_name=drug,
        ordered_datetime=at,
        status=OrderStatus.PLACED,
        route=route,
        **kw,
    )


def _norepinephrine(**kw) -> Order:
    return _order("ORD-NE", "Norepinephrine 0.1ug/kg/min IV drip", route="IV", at=_NE_START, **kw)


_HELD_DRUGS = {
    "ORD-AML": "Amlodipine 5mg PO daily",
    "ORD-HCTZ": "Hydrochlorothiazide 25mg PO daily",
    "ORD-NTG": "Nitroglycerin 0.3mg SL",
    "ORD-MET": "Metoprolol 25mg PO BID",
}


def _mar(orders: list[Order], day: int, patient: PatientProfile | None = None) -> list[MedicationAdministration]:
    return _generate_mar(
        patient or PatientProfile(patient_id="POP-3233"),
        orders,
        day,
        _ADMIT,
        roster=_StubRoster(),  # type: ignore[arg-type]
        rng=np.random.default_rng(0),
    )


def _home_orders() -> list[Order]:
    return [_order(oid, name, frequency_per_day=1) for oid, name in _HELD_DRUGS.items()]


def test_doses_during_a_norepinephrine_infusion_are_held_with_the_reason() -> None:
    reason = vasoactive_hold_rules().reason
    mars = _mar([*_home_orders(), _norepinephrine()], 2)
    held = {m.order_id for m in mars if m.status == "held"}
    assert held >= set(_HELD_DRUGS)
    assert {m.hold_reason for m in mars if m.order_id in _HELD_DRUGS} == {reason}
    # The infusion itself is given.
    assert any(m.order_id == "ORD-NE" and m.status in ("given", "refused") for m in mars)


def test_doses_before_the_infusion_starts_are_given() -> None:
    # Day 1 (2026-03-02) 08:00 doses precede the 10:00 start.
    mars = _mar([*_home_orders(), _norepinephrine()], 1)
    early = [m for m in mars if m.order_id in _HELD_DRUGS and m.scheduled_datetime < _NE_START]
    assert early and all(m.status != "held" for m in early)


def test_doses_resume_after_the_infusion_stops() -> None:
    ne = _norepinephrine(end_datetime=datetime(2026, 3, 3, 6, 0))
    mars = _mar([*_home_orders(), ne], 3)
    doses = [m for m in mars if m.order_id in _HELD_DRUGS]
    assert doses and all(m.status != "held" for m in doses)


def test_an_inotrope_infusion_also_holds() -> None:
    dobutamine = _order("ORD-DOB", "Dobutamine 5ug/kg/min IV drip", route="IV", at=_NE_START)
    mars = _mar([*_home_orders(), dobutamine], 2)
    assert {m.order_id for m in mars if m.status == "held"} >= set(_HELD_DRUGS)


@pytest.mark.parametrize(
    "order",
    [
        # An oral vasopressor (orthostatic hypotension, hepatorenal syndrome) is not shock support.
        _order("ORD-MID", "Midodrine 7.5mg PO TID", frequency_per_day=3),
        # A one-time epinephrine dose is not a running infusion.
        _order("ORD-EPI", "Epinephrine 0.3mg IM", route="IM", single_dose=True),
    ],
)
def test_no_hold_without_a_running_infusion(order: Order) -> None:
    assert vasoactive_infusions([order]) == ()
    mars = _mar([*_home_orders(), order], 2)
    assert all(m.status != "held" for m in mars if m.order_id in _HELD_DRUGS)


def test_drugs_outside_the_held_classes_are_given() -> None:
    infusions = vasoactive_infusions([_norepinephrine()])
    at = _NE_START + timedelta(hours=2)
    assert vasoactive_hold_reason("Atorvastatin 40mg", at, infusions) is None
    assert vasoactive_hold_reason("Amiodarone 150mg IV", at, infusions) is None
    assert vasoactive_hold_reason("Furosemide 40mg IV", at, infusions) == vasoactive_hold_rules().reason


def test_the_reason_has_an_english_and_a_japanese_display() -> None:
    reason = vasoactive_hold_rules().reason
    en, ja = hold_reason_display(reason, "en"), hold_reason_display(reason, "ja")
    assert en and ja and en != ja
    assert not any("぀" <= ch <= "ヿ" or "一" <= ch <= "鿿" for ch in en)
    assert not any("a" <= ch.lower() <= "z" for ch in ja)


def _vs(at: datetime, sbp: int | None = None, hr: int | None = None) -> VitalSignRecord:
    return VitalSignRecord(timestamp=at, systolic_bp=sbp, heart_rate=hr)


def _given(order_id: str, drug: str, at: datetime) -> MedicationAdministration:
    return MedicationAdministration(
        order_id=order_id, drug_name=drug, scheduled_datetime=at, actual_datetime=at, status="given"
    )


def test_vital_holds_read_the_latest_in_stay_vitals_before_the_dose() -> None:
    dose = datetime(2026, 3, 2, 8, 0)
    mars = [_given("ORD-AML", "Amlodipine 5mg PO daily", dose), _given("ORD-CAR", "Carvedilol 3.125mg PO BID", dose)]
    vitals = [
        _vs(dose - timedelta(hours=4), sbp=82, hr=90),
        _vs(dose - timedelta(hours=1), hr=46),
        _vs(dose + timedelta(hours=1), sbp=130),
    ]
    apply_vital_holds(mars, vitals, BaselineVitals(systolic_bp=130, heart_rate=70))
    assert [(m.status, m.hold_reason, m.actual_datetime) for m in mars] == [
        ("held", "SBP < 90", None),
        ("held", "HR < 50", None),
    ]


def test_a_normal_in_stay_pressure_overrides_a_low_baseline() -> None:
    dose = datetime(2026, 3, 2, 8, 0)
    mars = [_given("ORD-AML", "Amlodipine 5mg PO daily", dose)]
    apply_vital_holds(mars, [_vs(dose - timedelta(hours=2), sbp=128)], BaselineVitals(systolic_bp=85))
    assert mars[0].status == "given"


def test_the_baseline_stands_in_before_the_first_in_stay_vitals() -> None:
    dose = datetime(2026, 3, 1, 15, 0)
    mars = [_given("ORD-AML", "Amlodipine 5mg PO daily", dose)]
    apply_vital_holds(mars, [_vs(dose + timedelta(hours=1), sbp=128)], BaselineVitals(systolic_bp=85))
    assert (mars[0].status, mars[0].hold_reason) == ("held", "SBP < 90")


def test_refused_and_other_held_doses_are_left_as_recorded() -> None:
    dose = datetime(2026, 3, 2, 8, 0)
    refused = _given("ORD-AML", "Amlodipine 5mg PO daily", dose)
    refused.status, refused.actual_datetime = "refused", None
    k_held = _given("ORD-CAN", "Candesartan 8mg PO daily", dose)
    k_held.status, k_held.hold_reason, k_held.actual_datetime = "held", "K 6.4 mmol/L", None
    apply_vital_holds([refused, k_held], [_vs(dose - timedelta(hours=1), sbp=80)], BaselineVitals())
    assert (refused.status, refused.hold_reason) == ("refused", None)
    assert k_held.hold_reason == "K 6.4 mmol/L"


@pytest.mark.parametrize(("lang", "expected"), [("en", "on vasopressor"), ("ja", "昇圧薬")])
def test_progress_plan_lists_the_held_drug_with_the_localized_reason(lang: str, expected: str) -> None:
    from clinosim.modules.document.narrative.renderers._composers import compose_progress_plan_from_state

    reason = vasoactive_hold_rules().reason
    ctx = SimpleNamespace(
        target_lang=lang,
        day_index=2,
        procedures=[],
        medications=[
            {"drug_name": "Amlodipine", "day": 2, "status": "held", "hold_reason": reason},
            {"drug_name": "Norepinephrine", "day": 2, "status": "given"},
        ],
    )
    plan = compose_progress_plan_from_state(ctx)  # type: ignore[arg-type]
    held_part = plan.split("Held:" if lang == "en" else "休薬:")[1]
    assert expected in held_part
    assert hold_reason_display(reason, lang) in held_part
    if lang == "ja":
        assert reason not in plan
