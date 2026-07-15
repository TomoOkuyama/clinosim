"""Unit tests for `medication_flags_from_context` — Phase 2b on_warfarin
detection (chronic + in-hospital ramp at day ≥ 3). DOAC is intentionally
NOT detected (INR is not clinically monitored for DOAC).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime

import pytest

from clinosim.modules.physiology.engine import medication_flags_from_context


@dataclass
class _StubPatient:
    """Minimal stand-in for PatientProfile.current_medications consumers."""

    current_medications: list[str] = field(default_factory=list)


@dataclass
class _StubOrder:
    """Minimal stand-in for Order (medication-type) consumers."""

    display_name: str = ""
    ordered_datetime: datetime | None = None


@pytest.mark.unit
def test_chronic_warfarin_en_detected():
    p = _StubPatient(current_medications=["Warfarin 3mg"])
    assert medication_flags_from_context(p) == {"on_warfarin": True}


@pytest.mark.unit
def test_chronic_warfarin_jp_detected():
    p = _StubPatient(current_medications=["ワルファリン3mg"])
    assert medication_flags_from_context(p) == {"on_warfarin": True}


@pytest.mark.unit
def test_chronic_coumadin_detected_case_insensitive():
    p = _StubPatient(current_medications=["COUMADIN 5mg PO daily"])
    assert medication_flags_from_context(p) == {"on_warfarin": True}


@pytest.mark.unit
def test_chronic_apixaban_not_warfarin():
    p = _StubPatient(current_medications=["Apixaban 5mg"])
    assert medication_flags_from_context(p) == {"on_warfarin": False}


@pytest.mark.unit
def test_chronic_rivaroxaban_not_warfarin():
    p = _StubPatient(current_medications=["Rivaroxaban 20mg", "リバーロキサバン15mg"])
    assert medication_flags_from_context(p) == {"on_warfarin": False}


@pytest.mark.unit
def test_no_meds_returns_false():
    p = _StubPatient(current_medications=[])
    assert medication_flags_from_context(p) == {"on_warfarin": False}


@pytest.mark.unit
def test_none_patient_returns_false():
    assert medication_flags_from_context(None) == {"on_warfarin": False}


@pytest.mark.unit
def test_in_hospital_warfarin_day_2_not_yet():
    p = _StubPatient(current_medications=[])
    admission = date(2026, 6, 1)
    # warfarin ordered on day 0 (admission), current day = 2 → not yet therapeutic
    orders = [_StubOrder(display_name="Warfarin 3mg", ordered_datetime=datetime(2026, 6, 1, 10, 0))]
    flags = medication_flags_from_context(p, medication_orders=orders, admission_date=admission, current_day=2)
    assert flags == {"on_warfarin": False}


@pytest.mark.unit
def test_in_hospital_warfarin_day_3_active():
    p = _StubPatient(current_medications=[])
    admission = date(2026, 6, 1)
    orders = [_StubOrder(display_name="Warfarin 3mg", ordered_datetime=datetime(2026, 6, 1, 10, 0))]
    flags = medication_flags_from_context(p, medication_orders=orders, admission_date=admission, current_day=3)
    assert flags == {"on_warfarin": True}


@pytest.mark.unit
def test_in_hospital_apixaban_never_triggers():
    p = _StubPatient(current_medications=[])
    admission = date(2026, 6, 1)
    orders = [_StubOrder(display_name="Apixaban 5mg", ordered_datetime=datetime(2026, 6, 1, 10, 0))]
    flags = medication_flags_from_context(p, medication_orders=orders, admission_date=admission, current_day=7)
    assert flags == {"on_warfarin": False}


@pytest.mark.unit
def test_in_hospital_warfarin_ordered_day_5_current_day_6_not_yet():
    """warfarin ordered late (day 5); current day 6 → 1 day elapsed → not therapeutic."""
    p = _StubPatient(current_medications=[])
    admission = date(2026, 6, 1)
    orders = [_StubOrder(display_name="Warfarin 3mg", ordered_datetime=datetime(2026, 6, 6, 10, 0))]
    flags = medication_flags_from_context(p, medication_orders=orders, admission_date=admission, current_day=6)
    assert flags == {"on_warfarin": False}


@pytest.mark.unit
def test_chronic_overrides_in_hospital_gate():
    """Chronic warfarin is True even at current_day=1 (gate only applies to in-hospital path)."""
    p = _StubPatient(current_medications=["Warfarin 3mg"])
    admission = date(2026, 6, 1)
    flags = medication_flags_from_context(p, medication_orders=[], admission_date=admission, current_day=1)
    assert flags == {"on_warfarin": True}
