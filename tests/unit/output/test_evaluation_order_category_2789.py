"""Issue #2789: bedside eye examinations and peak-flow measurements are
evaluation procedures, not imaging studies or specimen tests."""

from __future__ import annotations

from datetime import datetime

import pytest

from clinosim.modules.output.fhir_r4.labs.service_request import _build_imaging_sr, _build_standalone_sr
from clinosim.types.encounter import Order, OrderStatus, OrderType

pytestmark = pytest.mark.unit


def _imaging_order(name: str) -> dict:
    return {
        "order_id": f"ORD-{name}",
        "patient_id": "P1",
        "encounter_id": "ENC-1",
        "order_type": "imaging",
        "display_name": name,
        "ordered_datetime": datetime(2025, 3, 1, 10, 0).isoformat(),
        "status": "resulted",
        "urgency": "routine",
    }


def _lab_sr(name: str, country: str) -> dict:
    order = Order(
        order_id=f"ORD-ENC-1-{name}",
        encounter_id="ENC-1",
        patient_id="pt-1",
        order_type=OrderType.LAB,
        order_code=name,
        display_name=name,
        ordered_datetime=datetime(2025, 3, 1, 9, 0),
        status=OrderStatus.RESULTED,
    )
    return _build_standalone_sr(order, "ja" if country == "jp" else "en", country)


@pytest.mark.parametrize("name", ["Slit_lamp_exam", "Fluorescein_stain"])
def test_an_eye_examination_is_an_evaluation_procedure(name: str) -> None:
    sr = _build_imaging_sr(_imaging_order(name), "en", "US")
    assert [c["code"] for c in sr["category"][0]["coding"]] == ["386053000"]
    assert sr["category"][0]["text"] == "Evaluation procedure"


@pytest.mark.parametrize("country", ["us", "jp"])
def test_peak_flow_is_a_pulmonary_function_evaluation(country: str) -> None:
    sr = _lab_sr("Peak_Expiratory_Flow", country)
    assert [c["code"] for c in sr["category"][0]["coding"]] == ["386053000", "PF"]


def test_a_specimen_test_stays_a_laboratory_order() -> None:
    sr = _lab_sr("K_stat", "us")
    assert [c["code"] for c in sr["category"][0]["coding"]] == ["108252007", "LAB"]


def test_an_imaging_study_stays_an_imaging_order() -> None:
    sr = _build_imaging_sr(_imaging_order("Chest_Xray"), "en", "US")
    assert [c["code"] for c in sr["category"][0]["coding"]] == ["363679005", "RAD"]


def test_a_bedside_examination_order_is_completed_without_a_study() -> None:
    """Issue #2796: no ImagingStudy is made for a bedside examination; its
    order is completed (done at the bedside), not revoked at discharge."""
    from types import SimpleNamespace

    from clinosim.modules.output.fhir_r4.labs.service_request import _build_imaging_service_requests

    ctx = SimpleNamespace(
        country="US",
        record={"extensions": {"imaging": []}, "encounters": [{"encounter_id": "ENC-1", "discharge_datetime": "x"}]},
    )
    orders = [
        {**_imaging_order("Slit_lamp_exam"), "status": "placed"},
        {**_imaging_order("CT_Head"), "status": "placed"},
    ]
    status = {sr["identifier"][0]["value"]: sr["status"] for sr in _build_imaging_service_requests(orders, ctx)}
    assert status == {"ORD-Slit_lamp_exam": "completed", "ORD-CT_Head": "revoked"}
