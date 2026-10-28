"""Chronic-medication monitoring follows guideline intervals (Issue #2143)."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from typing import Any

import pytest

from clinosim.modules.monitoring.enricher import enrich_medication_monitoring
from clinosim.modules.monitoring.mapping import load_medication_monitoring
from clinosim.types.encounter import EncounterType
from clinosim.types.patient import HomeMedication

pytestmark = pytest.mark.unit


def _monthly_records(drugs: list[str], months: int = 12) -> list[Any]:
    patient = SimpleNamespace(
        patient_id="POP-000777",
        sex="F",
        age=60,
        current_medications=[HomeMedication(drug_name=d, route="PO") for d in drugs],
        chronic_conditions=[],
    )
    records = []
    # Generation order is not chronological: the enricher must sort.
    for m in reversed(range(months)):
        enc = SimpleNamespace(
            encounter_id=f"ENC-777-{m:02d}",
            encounter_type=EncounterType.OUTPATIENT,
            admission_datetime=datetime(2024, 1 + m, 10, 9, 0),
            attending_physician_id="STAFF-DOC-001",
        )
        records.append(SimpleNamespace(patient=patient, encounters=[enc], orders=[], lab_results=[]))
    return records


def _draws(records: list[Any], analyte: str) -> list[int]:
    months = []
    for r in records:
        if any(getattr(o, "display_name", "") == analyte for o in r.orders):
            months.append(r.encounters[0].admission_datetime.month)
    return sorted(months)


def test_every_monitored_lab_has_an_interval() -> None:
    for drug, entry in load_medication_monitoring().items():
        for lab in entry["monitoring"]:
            assert int(lab["interval_months"]) >= 1, (drug, lab["lab"])


def test_tsh_every_six_months_inr_monthly() -> None:
    records = _monthly_records(["Levothyroxine 50mcg", "Warfarin 3mg"])
    enrich_medication_monitoring(SimpleNamespace(config=SimpleNamespace(country="US"), master_seed=42, records=records))
    assert _draws(records, "TSH") == [1, 7]
    assert len(_draws(records, "PT_INR")) == 12


def test_existing_result_counts_as_a_draw() -> None:
    records = _monthly_records(["Levothyroxine 50mcg"], months=4)
    feb = next(r for r in records if r.encounters[0].admission_datetime.month == 2)
    feb.lab_results.append(SimpleNamespace(lab_name="TSH", result_datetime=datetime(2024, 2, 10, 10, 0)))
    enrich_medication_monitoring(SimpleNamespace(config=SimpleNamespace(country="US"), master_seed=42, records=records))
    # January is drawn before February's own TSH; March / April fall within 6 months of February.
    assert _draws(records, "TSH") == [1]
