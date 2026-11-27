"""Issue #3837: how the sleep-study result is written in FHIR.

The AHI is a procedure-result Observation (category procedure), not a
laboratory result: no specimen, no analyzer method, no laboratory profile. Its
ServiceRequest is an evaluation procedure and its DiagnosticReport is the
polysomnography report (LOINC 28633-6).
"""

from __future__ import annotations

from datetime import datetime

import pytest

from clinosim.modules.output.fhir_r4.labs.diagnostic_report import (
    build_single_test_report,
    group_lab_orders,
    single_test_report_groups,
)
from clinosim.modules.output.fhir_r4.labs.observations import _build_lab_observation
from clinosim.modules.output.fhir_r4.labs.service_request import _build_standalone_sr
from clinosim.modules.output.fhir_r4.post_process import _lab_observation_needs_specimen
from clinosim.types.encounter import Order, OrderResult, OrderStatus, OrderType

pytestmark = pytest.mark.unit


def _obs(country: str) -> dict:
    order = {"display_name": "AHI", "ordered_datetime": "2026-05-12T10:00:00", "ordered_by": "DR-1"}
    result = {"lab_name": "AHI", "value": 22.4, "unit": "{events}/h", "result_datetime": "2026-05-12T10:30:00"}
    r = _build_lab_observation(
        order, result, patient_id="POP-1", index=1, country=country, patient_sex="M", encounter_id="ENC-001"
    )
    assert r is not None
    return r


def _order() -> Order:
    o = Order(
        order_id="ORD-ENC-1-AHI",
        encounter_id="ENC-1",
        patient_id="pt-1",
        order_type=OrderType.LAB,
        order_code="AHI",
        display_name="AHI",
        ordered_datetime=datetime(2026, 5, 12, 10, 0),
        status=OrderStatus.RESULTED,
    )
    o.result = OrderResult(lab_name="AHI", value=22.4, unit="{events}/h", result_datetime=datetime(2026, 5, 12, 10, 30))
    return o


@pytest.mark.parametrize("country", ["US", "JP"])
def test_ahi_observation(country: str) -> None:
    r = _obs(country)
    cats = [c["code"] for cc in r["category"] for c in cc["coding"]]
    assert "procedure" in cats and "laboratory" not in cats
    assert "method" not in r and "specimen" not in r
    assert _lab_observation_needs_specimen(r) is False
    assert [c["code"] for c in r["code"]["coding"] if c["system"] == "http://loinc.org"] == ["69990-0"]
    assert r["valueQuantity"]["code"] == "{events}/h"
    assert r["performer"] == [{"reference": "Practitioner/DR-1"}]
    assert "meta" not in r or not r["meta"].get("profile")


def test_ahi_observation_jp_text_is_japanese() -> None:
    assert "無呼吸" in _obs("JP")["code"]["text"]
    assert "apnea" in _obs("US")["code"]["text"].lower()


@pytest.mark.parametrize("country", ["US", "JP"])
def test_ahi_report_is_the_sleep_study(country: str) -> None:
    orders = [_order()]
    groups = single_test_report_groups(orders, group_lab_orders(orders, "ENC-1"), {})
    dr = build_single_test_report(groups[0], orders, "pt-1", "ENC-1", country, None)
    assert dr["code"]["coding"][0]["code"] == "28633-6"
    cats = [c["code"] for cc in dr["category"] for c in cc["coding"]]
    assert "LAB" not in cats
    assert not dr.get("meta", {}).get("profile")
    assert len(dr["result"]) == 1


@pytest.mark.parametrize("country", ["US", "JP"])
def test_ahi_service_request_is_an_evaluation_procedure(country: str) -> None:
    sr = _build_standalone_sr(_order(), "ja" if country == "JP" else "en", country.lower())
    codes = [c["code"] for cc in sr["category"] for c in cc["coding"]]
    assert "386053000" in codes


@pytest.mark.parametrize("country", ["US", "JP"])
def test_ahi_report_conclusion_prints_events_per_hour_without_braces_3926(country: str) -> None:
    orders = [_order()]
    groups = single_test_report_groups(orders, group_lab_orders(orders, "ENC-1"), {})
    dr = build_single_test_report(groups[0], orders, "pt-1", "ENC-1", country, None)
    conclusion = dr["conclusion"]
    assert "{" not in conclusion and "}" not in conclusion, conclusion
    assert "events/h" in conclusion
