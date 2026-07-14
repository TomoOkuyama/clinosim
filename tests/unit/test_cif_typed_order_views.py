"""session 48 cleanup (g.3):CIFPatientRecord.medication_orders / lab_orders /
imaging_orders 型付き view のテスト.

`orders` は mixed 単一 source of truth のまま。view は filter 済み read-only。
"""
from __future__ import annotations

import pytest


def _make_order(order_type):
    from clinosim.types.encounter import Order
    return Order(
        order_id="ord-1",
        order_type=order_type,
        display_name="test",
    )


@pytest.mark.unit
def test_medication_orders_filters_correctly():
    from clinosim.types.encounter import OrderType
    from clinosim.types.output import CIFPatientRecord
    rec = CIFPatientRecord(orders=[
        _make_order(OrderType.MEDICATION),
        _make_order(OrderType.LAB),
        _make_order(OrderType.MEDICATION),
        _make_order(OrderType.IMAGING),
    ])
    meds = rec.medication_orders
    assert len(meds) == 2
    assert all(o.order_type == OrderType.MEDICATION for o in meds)


@pytest.mark.unit
def test_lab_orders_filters_correctly():
    from clinosim.types.encounter import OrderType
    from clinosim.types.output import CIFPatientRecord
    rec = CIFPatientRecord(orders=[
        _make_order(OrderType.LAB),
        _make_order(OrderType.LAB),
        _make_order(OrderType.MEDICATION),
    ])
    labs = rec.lab_orders
    assert len(labs) == 2


@pytest.mark.unit
def test_imaging_orders_filters_correctly():
    from clinosim.types.encounter import OrderType
    from clinosim.types.output import CIFPatientRecord
    rec = CIFPatientRecord(orders=[
        _make_order(OrderType.IMAGING),
        _make_order(OrderType.LAB),
    ])
    imgs = rec.imaging_orders
    assert len(imgs) == 1
    assert imgs[0].order_type == OrderType.IMAGING


@pytest.mark.unit
def test_views_empty_when_no_orders():
    from clinosim.types.output import CIFPatientRecord
    rec = CIFPatientRecord()
    assert rec.medication_orders == []
    assert rec.lab_orders == []
    assert rec.imaging_orders == []


@pytest.mark.unit
def test_views_are_read_only_derived_from_orders():
    """view は property なので mutate しても orders には影響しない。"""
    from clinosim.types.encounter import OrderType
    from clinosim.types.output import CIFPatientRecord
    rec = CIFPatientRecord(orders=[_make_order(OrderType.LAB)])
    labs = rec.lab_orders
    labs.append(_make_order(OrderType.LAB))  # 別 list なので orders には反映しない
    assert len(rec.orders) == 1
    assert len(rec.lab_orders) == 1


@pytest.mark.unit
def test_order_type_value_helper_handles_enum_str_and_dict():
    from clinosim.types.encounter import OrderType
    from clinosim.types.output import _order_type_value
    assert _order_type_value(_make_order(OrderType.LAB)) == "lab"
    # dict fallback(JSON-deserialized CIF)
    assert _order_type_value({"order_type": "medication"}) == "medication"
    assert _order_type_value({"order_type": ""}) == ""
    assert _order_type_value({}) == ""
