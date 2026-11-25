"""Issue #3802: a questionnaire total score is no specimen test.

PHQ-9 / GAD-7 / C-SSRS / EPDS Observations (category ``survey``) carry no
specimen and no laboratory analyzer method; their ServiceRequest and
DiagnosticReport are not laboratory (specimen) orders or reports either.
Laboratory results are unchanged.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from clinosim.modules.output.fhir_r4.labs import observations as obs_mod
from clinosim.modules.output.fhir_r4.labs.diagnostic_report import (
    build_single_test_report,
    group_lab_orders,
    single_test_report_groups,
)
from clinosim.modules.output.fhir_r4.labs.observations import _build_lab_observation
from clinosim.modules.output.fhir_r4.labs.service_request import _build_standalone_sr
from clinosim.modules.output.fhir_r4.lib.common import QUESTIONNAIRE_SCORE_ANALYTES
from clinosim.modules.output.fhir_r4.post_process import _lab_observation_needs_specimen
from clinosim.types.encounter import Order, OrderStatus, OrderType

pytestmark = pytest.mark.unit

SCORES = ["PHQ-9", "GAD-7", "C-SSRS", "EPDS"]


def _obs(name: str, value: float, country: str) -> dict:
    order = {"display_name": name, "ordered_datetime": "2026-05-12T10:00:00"}
    result = {"lab_name": name, "value": value, "unit": "", "result_datetime": "2026-05-12T10:30:00"}
    resource = _build_lab_observation(
        order, result, patient_id="POP-000002", index=1, country=country, patient_sex="F", encounter_id="ENC-001"
    )
    assert resource is not None
    return resource


def _order(name: str) -> Order:
    from clinosim.types.encounter import OrderResult

    o = Order(
        order_id=f"ORD-ENC-1-{name}",
        encounter_id="ENC-1",
        patient_id="pt-1",
        order_type=OrderType.LAB,
        order_code=name,
        display_name=name,
        ordered_datetime=datetime(2026, 5, 12, 10, 0),
        status=OrderStatus.RESULTED,
    )
    o.result = OrderResult(lab_name=name, value=12.0, unit="", result_datetime=datetime(2026, 5, 12, 10, 30))
    return o


def test_the_score_set_has_one_definition() -> None:
    assert QUESTIONNAIRE_SCORE_ANALYTES == frozenset(SCORES)
    assert not hasattr(obs_mod, "_QUESTIONNAIRE_SCORE_ANALYTES")


@pytest.mark.parametrize("country", ["US", "JP"])
@pytest.mark.parametrize("name", SCORES)
def test_score_observation_has_no_analyzer_method_and_needs_no_specimen(name: str, country: str) -> None:
    r = _obs(name, 11.0, country)
    assert "method" not in r
    assert "specimen" not in r
    assert _lab_observation_needs_specimen(r) is False


@pytest.mark.parametrize("country", ["US", "JP"])
def test_chemistry_observation_keeps_method_and_specimen(country: str) -> None:
    r = _obs("Hb", 13.5, country)
    assert r["method"]["text"]
    assert _lab_observation_needs_specimen(r) is True


@pytest.mark.parametrize("country", ["us", "jp"])
@pytest.mark.parametrize("name", SCORES)
def test_score_order_is_an_evaluation_procedure(name: str, country: str) -> None:
    sr = _build_standalone_sr(_order(name), "ja" if country == "jp" else "en", country)
    assert [c["code"] for c in sr["category"][0]["coding"]] == ["386053000"]


@pytest.mark.parametrize("country", ["US", "JP"])
def test_score_report_is_not_a_laboratory_report(country: str) -> None:
    orders = [_order("EPDS")]
    groups = single_test_report_groups(orders, group_lab_orders(orders, "ENC-1"), {})
    assert len(groups) == 1
    dr = build_single_test_report(groups[0], orders, "pt-1", "ENC-1", country, performer_ref=None)
    codes = [c["code"] for cat in dr["category"] for c in cat["coding"]]
    assert codes == ["386053000"]
    assert not any("LabResult" in p for p in dr.get("meta", {}).get("profile", []))
    assert "specimen" not in dr


@pytest.mark.parametrize("country", ["US", "JP"])
def test_chemistry_report_stays_laboratory(country: str) -> None:
    orders = [_order("Hb")]
    groups = single_test_report_groups(orders, group_lab_orders(orders, "ENC-1"), {})
    dr = build_single_test_report(groups[0], orders, "pt-1", "ENC-1", country, performer_ref=None)
    assert "LAB" in [c["code"] for cat in dr["category"] for c in cat["coding"]]
