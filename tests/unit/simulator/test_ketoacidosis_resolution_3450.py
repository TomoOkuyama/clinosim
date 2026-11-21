"""Issue #3450: the DKA insulin infusion, saline and potassium orders end when
ketoacidosis resolves, and the stay switches to subcutaneous basal insulin."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from clinosim.simulator.ketoacidosis_resolution import (
    basal_regimen_entry,
    ketoacidosis_resolution_rules,
    ketoacidosis_resolved,
    ketoacidosis_transition_due,
    running_ketoacidosis_infusions,
    stop_ketoacidosis_infusions,
)
from clinosim.types.encounter import Order, OrderResult, OrderStatus, OrderType

pytestmark = pytest.mark.unit

ADMIT = datetime(2025, 3, 1, 9, 0)


def _order(drug_id: str, route: str = "IV", name: str = "x", single: bool = False) -> Order:
    return Order(
        order_id=f"O-{drug_id}-{name}",
        order_type=OrderType.MEDICATION,
        display_name=name,
        drug_id=drug_id,
        route=route,
        ordered_datetime=ADMIT,
        status=OrderStatus.PLACED,
        single_dose=single,
    )


def _lab(name: str, value: float, when: datetime) -> OrderResult:
    return OrderResult(lab_name=name, value=value, result_datetime=when)


def _day(n: int) -> datetime:
    return datetime(2025, 3, 1) + timedelta(days=n)


def _infusions() -> list[Order]:
    return [
        _order("insulin_regular_human"),
        _order("normal_saline", name="IV_fluid: NS 1000mL/h x 1h, then 500mL/h"),
        _order("potassium_chloride"),
    ]


def test_resolved_on_bicarbonate_or_ph() -> None:
    assert ketoacidosis_resolved([_lab("HCO3", 19.0, _day(1))], _day(2))
    assert ketoacidosis_resolved([_lab("pH", 7.31, _day(1))], _day(2))


def test_not_resolved_while_acidotic_or_without_labs() -> None:
    assert not ketoacidosis_resolved([], _day(2))
    assert not ketoacidosis_resolved([_lab("HCO3", 15.0, _day(1)), _lab("pH", 7.28, _day(1))], _day(2))


def test_latest_result_decides_and_future_results_are_unseen() -> None:
    labs = [_lab("HCO3", 20.0, _day(1)), _lab("HCO3", 12.0, _day(1) + timedelta(hours=5))]
    assert not ketoacidosis_resolved(labs, _day(2))
    assert not ketoacidosis_resolved([_lab("HCO3", 20.0, _day(2) + timedelta(hours=3))], _day(2))


def test_ketone_above_limit_blocks_resolution() -> None:
    labs = [_lab("HCO3", 20.0, _day(1)), _lab("Beta_hydroxybutyrate", 2.0, _day(1))]
    assert not ketoacidosis_resolved(labs, _day(2))
    assert ketoacidosis_resolved(
        [
            *labs,
            _lab(
                "Beta_hydroxybutyrate",
                0.4,
                _day(
                    1,
                )
                + timedelta(hours=2),
            ),
        ],
        _day(2),
    )


def test_transition_due_only_with_a_running_insulin_infusion() -> None:
    labs = [_lab("HCO3", 20.0, _day(1))]
    assert ketoacidosis_transition_due(_infusions(), labs, _day(2))
    assert not ketoacidosis_transition_due([_order("normal_saline")], labs, _day(2))
    assert not ketoacidosis_transition_due(_infusions(), [_lab("HCO3", 12.0, _day(1))], _day(2))


def test_cap_forces_the_transition() -> None:
    cap = ketoacidosis_resolution_rules().max_infusion_days
    acidotic = [_lab("HCO3", 12.0, _day(1))]
    assert not ketoacidosis_transition_due(_infusions(), acidotic, ADMIT.replace(hour=0) + timedelta(days=cap - 1))
    assert ketoacidosis_transition_due(_infusions(), acidotic, ADMIT + timedelta(days=cap))


def test_stop_ends_infusions_after_the_overlap_and_leaves_others() -> None:
    orders = [*_infusions(), _order("insulin_regular_human", name="bolus", single=True), _order("enoxaparin", "SC")]
    stopped = stop_ketoacidosis_infusions(orders, _day(2))
    assert len(stopped) == 3
    end = _day(2) + timedelta(hours=ketoacidosis_resolution_rules().overlap_hours)
    assert all(o.status == OrderStatus.STOPPED and o.end_datetime == end for o in stopped)
    assert orders[3].status == OrderStatus.PLACED and orders[4].status == OrderStatus.PLACED
    assert running_ketoacidosis_infusions(orders) == []


def test_sc_insulin_is_not_an_infusion() -> None:
    assert running_ketoacidosis_infusions([_order("insulin_regular_human", "SC")]) == []


def test_basal_entry_found_for_each_country() -> None:
    from clinosim.modules.disease.protocol import load_disease_protocol

    protocol = load_disease_protocol("diabetic_ketoacidosis")
    for country in ("us", "jp"):
        entry = basal_regimen_entry(protocol.drugs or {}, country)
        assert entry is not None and entry["drug_id"] == "insulin_glargine"
