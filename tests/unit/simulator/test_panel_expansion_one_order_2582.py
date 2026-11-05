"""A panel order is emitted as one panel ServiceRequest with its components (Issue #2582)."""

from __future__ import annotations

from datetime import datetime

import pytest

from clinosim.modules.output.fhir_r4.labs.service_request import _build_lab_service_requests
from clinosim.modules.output.fhir_r4.lib.context import BundleContext
from clinosim.simulator.daily_loop import _expand_panel_orders
from clinosim.types.encounter import Order, OrderStatus, OrderType

pytestmark = pytest.mark.unit


def _gas(name: str = "ABG_repeat") -> Order:
    return Order(
        order_id="ORD-ENC-1-MOD-D2-ABG",
        encounter_id="ENC-1",
        patient_id="pt-1",
        order_type=OrderType.LAB,
        display_name=name,
        urgency="stat",
        ordered_datetime=datetime(2025, 3, 3, 10, 0),
        status=OrderStatus.PLACED,
    )


def test_components_carry_the_canonical_panel() -> None:
    children = _expand_panel_orders([_gas()])["ORD-ENC-1-MOD-D2-ABG"]
    assert [c.display_name for c in children] == ["pH", "pCO2", "pO2", "HCO3"]
    assert {c.panel_key for c in children} == {"ABG"}


def test_the_components_are_one_gas_panel_service_request() -> None:
    children = _expand_panel_orders([_gas()])["ORD-ENC-1-MOD-D2-ABG"]
    ctx = BundleContext(
        record={"orders": children},
        country="us",
        roster_map={},
        hospital_config={},
        patient_data={},
        patient_id="pt-1",
        is_readmission=False,
        prior_encounter_id=None,
        primary_dx_code="",
        admit_dx_code="",
        admit_dx_system="",
        primary_enc_id="ENC-1",
        patient_sex="",
    )
    srs = _build_lab_service_requests(children, ctx)
    assert len(srs) == 1
    assert [c["code"] for c in srs[0]["code"]["coding"]] == ["24338-6"]
