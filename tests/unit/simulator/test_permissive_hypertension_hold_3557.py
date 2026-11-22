"""Issue #3557: scheduled antihypertensives are held while the permissive
hypertension order of an acute ischemic stroke admission is in its window and
the latest systolic pressure is below its limit."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from clinosim.locale.loader import hold_reason_display
from clinosim.simulator.medication_pipeline import apply_vital_holds
from clinosim.simulator.permissive_hypertension import PermissiveHypertension, permissive_hypertension_rules
from clinosim.types.encounter import MedicationAdministration, Order, OrderStatus, OrderType, VitalSignRecord
from clinosim.types.patient import BaselineVitals

pytestmark = pytest.mark.unit

_T0 = datetime(2026, 3, 1, 14, 0)
_BLOCK = {"sbp_limit_mmhg": 220.0, "sbp_limit_thrombolysed_mmhg": 185.0, "window_hours": 48.0}


def _bp_order(block: dict | None = None) -> Order:
    return Order(
        order_id="ORD-BP",
        order_type=OrderType.THERAPY,
        display_name="BP_management: Permissive hypertension",
        ordered_datetime=_T0,
        status=OrderStatus.PLACED,
        permissive_hypertension=dict(_BLOCK if block is None else block),
    )


def _alteplase() -> Order:
    return Order(
        order_id="ORD-TPA",
        order_type=OrderType.MEDICATION,
        display_name="Alteplase 0.9mg/kg IV",
        ordered_datetime=_T0,
        status=OrderStatus.PLACED,
        route="IV",
    )


def _mar(drug: str, at: datetime) -> MedicationAdministration:
    return MedicationAdministration(
        order_id="ORD-X", drug_name=drug, scheduled_datetime=at, actual_datetime=at, status="given"
    )


def _vs(at: datetime, sbp: int) -> VitalSignRecord:
    return VitalSignRecord(timestamp=at, systolic_bp=sbp)


_BASE = BaselineVitals()


def _run(drug: str, at: datetime, sbp: int, orders: list[Order]) -> MedicationAdministration:
    mar = _mar(drug, at)
    apply_vital_holds([mar], [_vs(at - timedelta(hours=1), sbp)], _BASE, orders)
    return mar


def test_antihypertensive_held_below_the_limit() -> None:
    mar = _run("Amlodipine 5mg PO daily", _T0 + timedelta(hours=6), 125, [_bp_order()])
    assert mar.status == "held"
    assert mar.hold_reason == permissive_hypertension_rules().reason
    assert mar.actual_datetime is None


def test_given_at_or_above_the_limit() -> None:
    assert _run("Amlodipine 5mg PO daily", _T0 + timedelta(hours=6), 225, [_bp_order()]).status == "given"


def test_given_after_the_window() -> None:
    assert _run("Amlodipine 5mg PO daily", _T0 + timedelta(hours=49), 125, [_bp_order()]).status == "given"


def test_given_without_the_order() -> None:
    assert _run("Amlodipine 5mg PO daily", _T0 + timedelta(hours=6), 125, []).status == "given"


def test_other_drugs_are_given() -> None:
    assert _run("Atorvastatin 40mg PO daily", _T0 + timedelta(hours=6), 125, [_bp_order()]).status == "given"


def test_thrombolysis_lowers_the_limit() -> None:
    orders = [_bp_order(), _alteplase()]
    at = _T0 + timedelta(hours=6)
    assert _run("Amlodipine 5mg PO daily", at, 200, orders).status == "given"
    assert _run("Amlodipine 5mg PO daily", at, 180, orders).status == "held"
    assert _run("Amlodipine 5mg PO daily", at, 200, [_bp_order()]).status == "held"


def test_reason_in_english_and_japanese() -> None:
    reason = permissive_hypertension_rules().reason
    en, ja = hold_reason_display(reason, "en"), hold_reason_display(reason, "ja")
    assert en and ja and en != ja
    assert not any("a" <= ch.lower() <= "z" for ch in ja)


def test_stroke_protocol_item_validates_and_reaches_the_order() -> None:
    from clinosim.modules.order import engine

    sup = next(s for s in _supportive("cerebral_infarction") if s["type"] == "BP_management")
    block = PermissiveHypertension.model_validate(sup["permissive_hypertension"])
    assert (block.sbp_limit_mmhg, block.sbp_limit_thrombolysed_mmhg) == (220, 185)
    assert engine is not None


def _supportive(disease_id: str) -> list[dict]:
    from pathlib import Path

    import yaml

    import clinosim.modules.disease as disease_pkg

    path = Path(disease_pkg.__file__).parent / "reference_data" / f"{disease_id}.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data["order_protocols"]["admission_orders"]["supportive"]
