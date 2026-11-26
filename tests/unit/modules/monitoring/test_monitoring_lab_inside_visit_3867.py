"""Issue #3867: a chronic-medication monitoring lab of an ambulatory visit is
ordered and resulted inside the visit; an admission keeps its 10-30 minute
offset."""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from clinosim.modules.monitoring.enricher import enrich_medication_monitoring
from clinosim.types.encounter import EncounterType
from clinosim.types.patient import HomeMedication

pytestmark = pytest.mark.unit

_START = datetime(2025, 7, 10, 10, 9)


def _record(pid: str, etype: EncounterType, minutes: int | None) -> SimpleNamespace:
    patient = SimpleNamespace(
        patient_id=pid,
        sex="F",
        age=60,
        height_cm=160.0,
        address=SimpleNamespace(country="US"),
        current_medications=[HomeMedication(drug_name="Warfarin 3mg", route="PO")],
        chronic_conditions=[],
    )
    encounter = SimpleNamespace(
        encounter_id=f"ENC-{pid}",
        encounter_type=etype,
        admission_datetime=_START,
        discharge_datetime=None if minutes is None else _START + timedelta(minutes=minutes),
    )
    return SimpleNamespace(patient=patient, encounters=[encounter], orders=[], lab_results=[])


def _run(rec: SimpleNamespace) -> None:
    enrich_medication_monitoring(SimpleNamespace(config=SimpleNamespace(country="US"), master_seed=42, records=[rec]))


def test_short_outpatient_visit_gets_labs_inside_its_period() -> None:
    seen = 0
    for i in range(60):
        rec = _record(f"POP-{i:04d}", EncounterType.OUTPATIENT, 12)
        _run(rec)
        end = _START + timedelta(minutes=12)
        for o in rec.orders:
            seen += 1
            assert _START <= o.ordered_datetime <= end
            assert o.ordered_datetime <= o.result.result_datetime <= end
    assert seen


def test_emergency_visit_labs_stay_inside_the_visit() -> None:
    for i in range(30):
        rec = _record(f"POP-{i:04d}", EncounterType.EMERGENCY, 90)
        _run(rec)
        end = _START + timedelta(minutes=90)
        for o in rec.orders:
            assert o.ordered_datetime <= o.result.result_datetime <= end


def test_admission_keeps_the_ten_to_thirty_minute_offset() -> None:
    seen = 0
    for i in range(30):
        rec = _record(f"POP-{i:04d}", EncounterType.INPATIENT, 5 * 24 * 60)
        _run(rec)
        for o in rec.orders:
            seen += 1
            assert timedelta(minutes=10) <= o.ordered_datetime - _START < timedelta(minutes=30)
            assert o.result.result_datetime - o.ordered_datetime == timedelta(hours=2)
    assert seen


def test_visit_without_an_end_keeps_the_legacy_offset() -> None:
    rec = _record("POP-0001", EncounterType.OUTPATIENT, None)
    _run(rec)
    assert rec.orders
    for o in rec.orders:
        assert timedelta(minutes=10) <= o.ordered_datetime - _START < timedelta(minutes=30)
