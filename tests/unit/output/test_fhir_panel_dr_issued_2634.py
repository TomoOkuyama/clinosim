"""Issue #2634: a lab panel report is issued when its results are, not at midnight."""

from __future__ import annotations

import pytest

from clinosim.modules.output.fhir_r4.labs.diagnostic_report import build_lab_panel_reports
from clinosim.modules.output.fhir_r4.labs.service_request import _bb_service_requests
from clinosim.modules.output.fhir_r4.lib.context import BundleContext

pytestmark = pytest.mark.unit

_RESULTED = ["2026-06-29T08:40:00", "2026-06-29T08:52:00", "2026-06-29T08:45:00", "2026-06-29T08:47:00"]


def _ctx() -> BundleContext:
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
            "result": {"result_datetime": _RESULTED[i], "lab_name": name, "value": 1.0, "unit": "u"},
        }
        for i, name in enumerate(["WBC", "Hb", "Hct", "Plt"])
    ]
    return BundleContext(
        record={"orders": orders},
        country="us",
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


def test_a_panel_report_is_issued_at_its_latest_result() -> None:
    [dr] = build_lab_panel_reports(_ctx())
    assert dr["issued"].startswith("2026-06-29T08:52:00")
    assert dr["effectiveDateTime"] <= dr["issued"]


def test_the_panel_order_keeps_its_order_time() -> None:
    [sr] = _bb_service_requests(_ctx())
    assert sr["authoredOn"].startswith("2026-06-29T08:05")


def test_a_panel_report_is_effective_at_its_own_draw_not_a_later_order_that_day() -> None:
    ctx = _ctx()
    later = dict(ctx.record["orders"][0])
    later.update(
        order_id="O-late",
        display_name="Troponin_I",
        order_code="Troponin_I",
        panel_key="",
        ordered_datetime="2026-06-29T21:00:00",
        result={"result_datetime": "2026-06-29T21:40:00", "lab_name": "Troponin_I", "value": 0.1, "unit": "ng/mL"},
    )
    ctx.record["orders"].append(later)
    cbc = next(r for r in build_lab_panel_reports(ctx) if r["code"]["coding"][0]["code"] == "58410-2")
    assert cbc["effectiveDateTime"].startswith("2026-06-29T08:05")
    assert cbc["effectiveDateTime"] <= cbc["issued"]
