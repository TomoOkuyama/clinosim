"""Issue #2586: every resulted lab order is reported through a DiagnosticReport.

A panel order is reported by its panel DiagnosticReport; a stand-alone test
(troponin, lactate, a single creatinine) gets a report of its own, ``basedOn``
its order and carrying its one result.
"""

from __future__ import annotations

import pytest

from clinosim.modules.output.fhir_r4.labs.diagnostic_report import build_lab_panel_reports
from clinosim.modules.output.fhir_r4.labs.observations import _bb_labs
from clinosim.modules.output.fhir_r4.labs.service_request import _bb_service_requests
from clinosim.modules.output.fhir_r4.lib.context import BundleContext

pytestmark = pytest.mark.unit

_ENC = "enc1"
_PT = "pt1"


def _order(order_id: str, name: str, ordered: str, resulted: str, value: float | None = 1.0, panel_key: str = ""):
    return {
        "order_id": order_id,
        "encounter_id": _ENC,
        "patient_id": _PT,
        "order_type": "lab",
        "order_code": name,
        "display_name": name,
        "urgency": "stat",
        "clinical_intent": "",
        "ordered_datetime": ordered,
        "ordered_by": "doc1",
        "status": "resulted",
        "panel_key": panel_key,
        "result": {"result_datetime": resulted, "lab_name": name, "value": value, "unit": "ng/mL", "flag": "H"},
    }


def _ctx(orders: list[dict], country: str = "us") -> BundleContext:
    return BundleContext(
        record={"orders": orders},
        country=country,
        roster_map={},
        hospital_config={},
        patient_data={},
        patient_id=_PT,
        is_readmission=False,
        prior_encounter_id=None,
        primary_dx_code="",
        admit_dx_code="",
        admit_dx_system="",
        primary_enc_id=_ENC,
        patient_sex="",
    )


def _troponin() -> dict:
    return _order("O-trop", "Troponin_I", "2026-06-29T08:05:00", "2026-06-29T09:10:00", value=0.42)


def test_a_single_test_order_gets_one_report_with_its_one_result() -> None:
    ctx = _ctx([_troponin()])
    reports = build_lab_panel_reports(ctx)
    [sr] = _bb_service_requests(ctx)
    [obs] = _bb_labs(ctx)

    assert len(reports) == 1
    dr = reports[0]
    assert dr["basedOn"] == [{"reference": f"ServiceRequest/{sr['id']}"}]
    assert dr["result"] == [{"reference": f"Observation/{obs['id']}"}]
    assert dr["status"] == "final"
    assert dr["code"]["coding"] == sr["code"]["coding"]
    assert dr["effectiveDateTime"].startswith("2026-06-29T08:05")
    assert dr["issued"].startswith("2026-06-29T09:10")
    assert dr["conclusionCode"][0]["coding"][0]["code"] == "263654008"  # abnormal


def test_a_single_test_report_does_not_move_the_order_time() -> None:
    """The report is issued after the order, so the order's authoredOn stays put."""
    ctx = _ctx([_troponin()])
    [sr] = _bb_service_requests(ctx)
    assert sr["authoredOn"].startswith("2026-06-29T08:05")


def test_an_order_without_a_value_gets_no_report() -> None:
    """No Observation is emitted for it, so a report would have nothing to carry."""
    ctx = _ctx([_order("O-x", "Troponin_I", "2026-06-29T08:05:00", "2026-06-29T09:10:00", value=None)])
    assert build_lab_panel_reports(ctx) == []


def test_tests_grouped_into_a_panel_report_get_no_second_report() -> None:
    names = ["WBC", "Hb", "Hct", "Plt"]
    orders = [_order(f"O{i}", n, "2026-06-29T08:05:00", "2026-06-29T08:50:00") for i, n in enumerate(names)]
    orders.append(_troponin())
    reports = build_lab_panel_reports(_ctx(orders))
    results_per_report = sorted(len(r["result"]) for r in reports)
    assert results_per_report == [1, 4]
    covered = [ref["reference"] for r in reports for ref in r["result"]]
    assert len(covered) == len(set(covered)) == 5


def test_single_test_report_ids_are_distinct_and_stable() -> None:
    orders = [
        _troponin(),
        _order("O-lac", "Lactate", "2026-06-29T08:05:00", "2026-06-29T08:30:00", value=3.1),
    ]
    first = [r["id"] for r in build_lab_panel_reports(_ctx(orders))]
    second = [r["id"] for r in build_lab_panel_reports(_ctx(orders))]
    assert first == second
    assert len(set(first)) == 2


def test_a_jp_single_test_report_carries_the_jp_core_profile() -> None:
    [dr] = build_lab_panel_reports(_ctx([_troponin()], country="jp"))
    assert dr["meta"]["profile"] == ["http://jpfhir.jp/fhir/core/StructureDefinition/JP_DiagnosticReport_LabResult"]


def test_a_single_test_report_is_titled_like_its_observation() -> None:
    """The report's text is the analyte's coded display, not the short prose form ("K")."""
    ctx = _ctx([_order("O-k", "K", "2026-06-29T08:05:00", "2026-06-29T08:40:00", value=5.9)])
    [dr] = build_lab_panel_reports(ctx)
    [obs] = _bb_labs(ctx)
    assert dr["code"]["text"] == obs["code"]["text"]
    assert dr["code"]["text"] != "K"


def test_a_jp_single_test_report_is_titled_in_japanese() -> None:
    ctx = _ctx([_order("O-k", "K", "2026-06-29T08:05:00", "2026-06-29T08:40:00", value=5.9)], country="jp")
    [dr] = build_lab_panel_reports(ctx)
    [obs] = _bb_labs(ctx)
    assert dr["code"]["text"] == obs["code"]["text"]
