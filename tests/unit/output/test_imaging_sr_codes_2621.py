"""Issue #2621: every imaging ServiceRequest carries the study's procedure code; ECG is not imaging."""

from __future__ import annotations

from datetime import datetime

import pytest

from clinosim.modules.output.fhir_r4.labs.service_request import _build_imaging_sr

pytestmark = pytest.mark.unit


def _order(name: str) -> dict:
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


@pytest.mark.parametrize(
    ("name", "loinc", "site"),
    [
        ("Chest_Xray", "42272-5", "51185008"),  # Issue #2699: 2 views (PA + lateral) by default
        ("CT_Head", "30799-1", "69536005"),
        ("Ankle_Xray", "36294-7", "70258002"),
        ("CT_abdomen_pelvis_with_contrast", "36813-4", "818982008"),
        ("Echocardiogram", "59281-6", "80891009"),
    ],
)
def test_an_imaging_order_is_coded_with_its_procedure(name: str, loinc: str, site: str) -> None:
    sr = _build_imaging_sr(_order(name), "en", "US")
    assert sr["code"]["coding"][0] == {
        "system": "http://loinc.org",
        "code": loinc,
        "display": sr["code"]["coding"][0]["display"],
    }
    assert sr["code"]["text"] != name  # readable, not the internal order name
    assert sr["bodySite"][0]["coding"][0]["code"] == site
    assert [c["code"] for c in sr["category"][0]["coding"]] == ["363679005", "RAD"]


@pytest.mark.parametrize("name", ["ECG", "ECG_12lead"])
def test_an_ecg_is_an_electrocardiac_study(name: str) -> None:
    sr = _build_imaging_sr(_order(name), "en", "US")
    assert sr["code"]["coding"][0]["code"] == "11524-6"
    assert [c["code"] for c in sr["category"][0]["coding"]] == ["386053000", "EC"]
