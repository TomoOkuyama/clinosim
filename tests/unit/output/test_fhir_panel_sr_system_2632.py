"""Issue #2632: a panel lab order is coded under the LOINC system on every locale."""

from __future__ import annotations

import pytest

from clinosim.modules.output.fhir_r4.labs.service_request import _bb_service_requests
from clinosim.modules.output.fhir_r4.lib.context import BundleContext

pytestmark = pytest.mark.unit


def _ctx(country: str) -> BundleContext:
    orders = [
        {
            "order_id": f"O{i}",
            "encounter_id": "enc1",
            "patient_id": "pt1",
            "order_type": "lab",
            "order_code": name,
            "display_name": name,
            "urgency": "routine",
            "clinical_intent": "",
            "ordered_datetime": "2026-06-29T08:05:00",
            "ordered_by": "doc1",
            "status": "resulted",
            "panel_key": "CBC",
            "result": {"result_datetime": "2026-06-29T08:50:00", "lab_name": name, "value": 1.0, "unit": "u"},
        }
        for i, name in enumerate(["WBC", "Hb", "Hct", "Plt"])
    ]
    return BundleContext(
        record={"orders": orders},
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


@pytest.mark.parametrize(
    ("country", "text"),
    [("us", "Complete blood count (hemogram) panel - Blood by Automated count"), ("jp", "血算 (CBC)")],
)
def test_a_cbc_order_is_coded_in_loinc_with_a_readable_name(country: str, text: str) -> None:
    [sr] = _bb_service_requests(_ctx(country))
    [coding] = sr["code"]["coding"]
    assert (coding["system"], coding["code"]) == ("http://loinc.org", "58410-2")
    assert sr["code"]["text"] == text  # the panel report's text (lab_panels.yaml display)
