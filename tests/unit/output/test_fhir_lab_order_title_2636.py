"""Issue #2636: a lab order is titled like the result it produces."""

from __future__ import annotations

import pytest

from clinosim.modules.output.fhir_r4.labs.observations import _bb_labs
from clinosim.modules.output.fhir_r4.labs.service_request import _bb_service_requests
from clinosim.modules.output.fhir_r4.lib.context import BundleContext

pytestmark = pytest.mark.unit


def _ctx(name: str, country: str, resulted: bool = True) -> BundleContext:
    order = {
        "order_id": "O1",
        "encounter_id": "enc1",
        "patient_id": "pt1",
        "order_type": "lab",
        "order_code": name,
        "display_name": name,
        "urgency": "stat",
        "clinical_intent": "",
        "ordered_datetime": "2026-06-29T08:05:00",
        "ordered_by": "doc1",
        "status": "resulted" if resulted else "placed",
        "panel_key": "",
        "result": {"result_datetime": "2026-06-29T08:40:00", "lab_name": name, "value": 4.1, "unit": "mmol/L"}
        if resulted
        else None,
    }
    return BundleContext(
        record={"orders": [order]},
        country=country,
        roster_map={},
        hospital_config={},
        patient_data={},
        patient_id="pt1",
        is_readmission=False,
        prior_encounter_id=None,
        primary_dx_code="",
        admit_dx_code="",
        admit_dx_system="",
        primary_enc_id="enc1",
        patient_sex="",
    )


@pytest.mark.parametrize("country", ["us", "jp"])
@pytest.mark.parametrize("name", ["K", "Creatinine", "WBC", "Troponin_I"])
def test_an_order_is_titled_like_its_observation(name: str, country: str) -> None:
    ctx = _ctx(name, country)
    [sr] = _bb_service_requests(ctx)
    [obs] = _bb_labs(ctx)
    assert sr["code"]["text"] == obs["code"]["text"]


def test_an_unresulted_order_is_titled_like_a_result_would_be() -> None:
    [pending] = _bb_service_requests(_ctx("K", "us", resulted=False))
    [done] = _bb_service_requests(_ctx("K", "us"))
    assert pending["code"]["text"] == done["code"]["text"] != "K"
