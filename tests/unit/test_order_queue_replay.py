"""Unit tests for `order/engine.py` queue-replay helpers (Issue #761)."""

from __future__ import annotations

from datetime import datetime

import numpy as np
import pytest

from clinosim.modules.facility.hospital_state import HospitalState, load_hospital_operations
from clinosim.modules.order.engine import (
    calculate_result_time_from_state,
    order_resource_type,
    replay_order_to_state,
)
from clinosim.types.encounter import Order, OrderType

pytestmark = pytest.mark.unit


def _order(order_type: OrderType, display_name: str, urgency: str = "routine") -> Order:
    return Order(
        order_type=order_type,
        display_name=display_name,
        urgency=urgency,
        ordered_datetime=datetime(2025, 3, 1, 10, 0),
    )


class TestOrderResourceType:
    def test_lab_maps_to_lab(self):
        assert order_resource_type(_order(OrderType.LAB, "CBC")) == "lab"

    def test_imaging_mri(self):
        assert order_resource_type(_order(OrderType.IMAGING, "MRI Head")) == "mri"

    def test_imaging_ct(self):
        assert order_resource_type(_order(OrderType.IMAGING, "CT Abdomen")) == "ct"

    def test_imaging_xray_variants(self):
        assert order_resource_type(_order(OrderType.IMAGING, "Chest X-Ray")) == "xray"
        assert order_resource_type(_order(OrderType.IMAGING, "XRAY Wrist")) == "xray"
        # "CHEST" alone (without X-Ray) still routes to xray (bare chest imaging fallback).
        assert order_resource_type(_order(OrderType.IMAGING, "Chest Study")) == "xray"

    def test_imaging_ultrasound_variants(self):
        assert order_resource_type(_order(OrderType.IMAGING, "Echocardiogram")) == "ultrasound"
        assert order_resource_type(_order(OrderType.IMAGING, "Abdominal Ultrasound")) == "ultrasound"

    def test_imaging_default_xray(self):
        # Unrecognised imaging modality falls back to xray (matches
        # calculate_result_time_from_state's default_imaging branch).
        assert order_resource_type(_order(OrderType.IMAGING, "Nuclear Scan")) == "xray"

    def test_non_scheduled_returns_none(self):
        assert order_resource_type(_order(OrderType.MEDICATION, "Aspirin 81mg")) is None
        assert order_resource_type(_order(OrderType.DIET, "NPO")) is None


class TestReplayOrderToState:
    def test_lab_order_bumps_lab_queue(self):
        hs = HospitalState()
        ops = load_hospital_operations()
        before = hs.lab_queue
        replay_order_to_state(_order(OrderType.LAB, "BMP"), hs, ops)
        assert hs.lab_queue > before

    def test_medication_order_leaves_queue_unchanged(self):
        hs = HospitalState()
        ops = load_hospital_operations()
        before = (hs.lab_queue, hs.ct_queue, hs.mri_queue)
        replay_order_to_state(_order(OrderType.MEDICATION, "Insulin"), hs, ops)
        assert (hs.lab_queue, hs.ct_queue, hs.mri_queue) == before

    def test_no_op_when_hospital_state_is_none(self):
        # Must not raise; used on the legacy no-state path.
        replay_order_to_state(_order(OrderType.LAB, "CBC"), None, {})

    def test_replay_matches_cold_path_state_delta(self):
        # Issue #761 core: after N cold `calculate_result_time_from_state`
        # calls, hospital_state has some queue and staffing signature. A
        # subsequent run that goes through `replay_order_to_state` (no RNG,
        # no delay calc) for the SAME orders arrives at the SAME
        # hospital_state — that is what allows a cache-hit admission's
        # queue increments to be replayed byte-identically on the memo
        # side.
        ops = load_hospital_operations()
        orders = [_order(OrderType.LAB, f"LAB-{i}") for i in range(5)]
        orders.extend([_order(OrderType.IMAGING, "CT Head") for _ in range(2)])

        cold = HospitalState()
        rng = np.random.default_rng(42)
        for o in orders:
            calculate_result_time_from_state(o, cold, ops, rng)

        replay = HospitalState()
        for o in orders:
            replay_order_to_state(o, replay, ops)

        # The RNG-driven `delay` doesn't influence hospital_state, so cold
        # and replay must land on identical queue + staffing state.
        for attr in (
            "lab_queue",
            "ct_queue",
            "mri_queue",
            "xray_queue",
            "ultrasound_queue",
            "or_queue",
            "bed_occupancy",
            "ed_crowding",
            "lab_staff",
            "radiology_staff",
            "nursing_staff",
            "pharmacy_staff",
            "or_staff",
            "timestamp",
        ):
            assert getattr(cold, attr) == getattr(replay, attr), (
                f"{attr}: cold={getattr(cold, attr)} replay={getattr(replay, attr)}"
            )
