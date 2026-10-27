"""PRN analgesics and benzodiazepines follow pain and autonomic symptoms (#2085)."""

from __future__ import annotations

from datetime import datetime

import pytest

from clinosim.modules.order.engine import parse_dose_string
from clinosim.simulator.medication_pipeline import generate_prn_administrations, prn_category
from clinosim.types.clinical import PhysiologicalState
from clinosim.types.encounter import Order, OrderStatus, OrderType, VitalSignRecord

pytestmark = pytest.mark.unit


def test_parser_keeps_prn() -> None:
    parsed = parse_dose_string("1000mg IV q6h PRN")
    assert parsed["frequency"] == "Q6H PRN" and parsed["frequency_per_day"] == 4
    assert parse_dose_string("500mg PO BID")["frequency"] == "BID"


def test_prn_categories() -> None:
    assert prn_category("Acetaminophen") == "non_opioid"
    assert prn_category("Morphine") == "opioid"
    assert prn_category("Lorazepam") == "benzodiazepine"
    assert prn_category("Ondansetron") is None


def _order(name: str, freq: str, per_day: int, dose: float = 1000.0) -> Order:
    return Order(
        order_id=f"ORD-{name}",
        patient_id="P1",
        order_type=OrderType.MEDICATION,
        display_name=name,
        status=OrderStatus.PLACED,
        frequency=freq,
        frequency_per_day=per_day,
        dose_quantity=dose,
        dose_unit="mg",
        route="IV",
    )


def _vitals(*pains: int) -> list[VitalSignRecord]:
    return [
        VitalSignRecord(timestamp=datetime(2026, 5, 1, 2 + 4 * i, 0), pain_score=p, measured_by="NS-1")
        for i, p in enumerate(pains)
    ]


def test_analgesic_given_only_when_pain_reaches_threshold_and_interval_respected() -> None:
    apap = _order("Acetaminophen", "Q6H PRN", 4)
    last: dict[str, datetime] = {}
    mars = generate_prn_administrations([apap], _vitals(2, 6, 7, 5, 3, 8), PhysiologicalState(), last)
    times = [m.actual_datetime.hour for m in mars]
    assert times == [6, 14, 22]  # pain >= 4 at 06, 10, 14, 22 but q6h spacing skips 10


def test_opioid_needs_severe_pain() -> None:
    morphine = _order("Morphine", "Q4H PRN", 6, dose=2.0)
    mars = generate_prn_administrations([morphine], _vitals(5, 6, 8), PhysiologicalState(), {})
    assert [m.actual_datetime.hour for m in mars] == [10]


def test_benzodiazepine_follows_sympathetic_activation() -> None:
    lorazepam = _order("Lorazepam", "Q1H PRN", 24, dose=2.0)
    calm = generate_prn_administrations([lorazepam], _vitals(0, 0, 0), PhysiologicalState(), {})
    agitated = generate_prn_administrations(
        [lorazepam], _vitals(0, 0, 0), PhysiologicalState(sympathetic_activation=0.5), {}
    )
    assert calm == [] and len(agitated) == 3
