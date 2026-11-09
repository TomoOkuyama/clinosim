"""Issue #3019: a monitoring eGFR (DOAC renal-clearance check) is the
country's equation on the creatinine drawn the same day, like the eGFR of
every other path."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from clinosim.modules.monitoring.enricher import enrich_medication_monitoring
from clinosim.modules.physiology.egfr import estimated_gfr
from clinosim.types.encounter import EncounterType, Order, OrderResult, OrderStatus, OrderType
from clinosim.types.patient import HomeMedication

pytestmark = pytest.mark.unit

_VISIT = datetime(2025, 3, 15, 10, 0)


def _record(pid: str, country: str) -> SimpleNamespace:
    patient = SimpleNamespace(
        patient_id=pid,
        sex="F",
        age=78,
        height_cm=150.0,
        address=SimpleNamespace(country=country),
        current_medications=[HomeMedication(drug_name="Apixaban 5mg", route="PO")],
        chronic_conditions=[],
    )
    creatinine = Order(
        order_id=f"ORD-{pid}-CR",
        display_name="Creatinine",
        order_type=OrderType.LAB,
        status=OrderStatus.RESULTED,
        result=OrderResult(result_datetime=_VISIT.replace(hour=11), lab_name="Creatinine", value=1.62, unit="mg/dL"),
    )
    encounter = SimpleNamespace(
        encounter_id=f"ENC-{pid}", encounter_type=EncounterType.OUTPATIENT, admission_datetime=_VISIT
    )
    return SimpleNamespace(
        patient=patient, encounters=[encounter], orders=[creatinine], lab_results=[creatinine.result]
    )


@pytest.mark.parametrize("country", ["JP", "US"])
def test_monitoring_egfr_follows_the_visit_creatinine(country: str) -> None:
    egfrs = []
    for i in range(30):  # the DOAC check fires on a share of visits
        rec = _record(f"POP-{i:04d}", country)
        enrich_medication_monitoring(
            SimpleNamespace(config=SimpleNamespace(country=country), master_seed=42, records=[rec])
        )
        egfrs += [o.result for o in rec.orders if o.result is not None and o.result.lab_name == "eGFR"]
    assert egfrs, "no monitoring eGFR was injected"
    expected = round(estimated_gfr(1.62, 78, "F", 150.0, country) or 0)
    assert {r.value for r in egfrs} == {expected}
