"""Phase 1 of Issue #1698 — specialty routing fan-out helper unit tests.

Tests the `_specialty_fanout_tick(patient, chronic_event_time)` helper
directly without running a full simulation. The helper returns the list
of specialty-encounter synthesis orders for a given chronic_followup
tick, and updates the per-patient dedup tracker in place.
"""

from __future__ import annotations

from datetime import date, datetime

import pytest

from clinosim.locale.loader import load_specialty_routing
from clinosim.simulator.outpatient import _specialty_fanout_tick
from clinosim.types.patient import PatientProfile

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _clear() -> None:
    load_specialty_routing.cache_clear()
    yield
    load_specialty_routing.cache_clear()


def _profile(chronic_codes: list[str], patient_id: str = "pt-fanout") -> PatientProfile:
    from clinosim.types.patient import ChronicCondition

    p = PatientProfile(
        patient_id=patient_id,
        age=55,
        sex="M",
        date_of_birth=date(1969, 1, 1),
    )
    p.chronic_conditions = [ChronicCondition(code=c, system="icd-10-cm") for c in chronic_codes]
    return p


def test_c_code_patient_emits_oncology_once_per_year() -> None:
    """C50 patient: first chronic_followup tick in a year emits oncology;
    subsequent ticks in the SAME year emit nothing (annual dedup)."""
    patient = _profile(["C50.9"])
    tick1 = _specialty_fanout_tick(patient, datetime(2024, 3, 15))
    specialties1 = [s[0] for s in tick1]
    assert "oncology" in specialties1

    tick2 = _specialty_fanout_tick(patient, datetime(2024, 11, 30))
    specialties2 = [s[0] for s in tick2]
    assert "oncology" not in specialties2, "C50 patient must not get second oncology visit in same year"

    tick3 = _specialty_fanout_tick(patient, datetime(2025, 2, 1))
    specialties3 = [s[0] for s in tick3]
    assert "oncology" in specialties3, "C50 patient must get oncology in next year"


def test_multi_cancer_patient_single_oncology_per_year() -> None:
    """C50 + C18 patient (two cancers both route to oncology) sees ONE
    oncology visit per year, not two."""
    patient = _profile(["C50.9", "C18.9"])
    tick = _specialty_fanout_tick(patient, datetime(2024, 3, 15))
    onco_count = sum(1 for s in tick if s[0] == "oncology")
    assert onco_count == 1, f"expected 1 oncology emit, got {onco_count}: {tick}"


def test_non_routing_table_cohort_emits_nothing() -> None:
    """Patient with only I10 + E78 + E66.9 (not in Phase 1 routing table)
    emits zero specialty visits."""
    patient = _profile(["I10", "E78", "E66.9"])
    tick = _specialty_fanout_tick(patient, datetime(2024, 3, 15))
    assert tick == []


def test_cardiology_semi_annual_dedup() -> None:
    """I48 patient: emit in H1 2024, skip remaining H1 ticks, emit again in H2."""
    patient = _profile(["I48"])
    t1 = _specialty_fanout_tick(patient, datetime(2024, 2, 10))
    assert any(s[0] == "cardiology" for s in t1)
    t2 = _specialty_fanout_tick(patient, datetime(2024, 5, 20))
    assert not any(s[0] == "cardiology" for s in t2)
    t3 = _specialty_fanout_tick(patient, datetime(2024, 9, 1))
    assert any(s[0] == "cardiology" for s in t3)


def test_psychiatry_quarterly_dedup() -> None:
    """F32 patient: emit in Q1 2024, skip Q1 extras, emit Q2."""
    patient = _profile(["F32"])
    t1 = _specialty_fanout_tick(patient, datetime(2024, 1, 15))
    assert any(s[0] == "psychiatry" for s in t1)
    t2 = _specialty_fanout_tick(patient, datetime(2024, 2, 28))
    assert not any(s[0] == "psychiatry" for s in t2)
    t3 = _specialty_fanout_tick(patient, datetime(2024, 4, 10))
    assert any(s[0] == "psychiatry" for s in t3)


def test_multi_specialty_patient_fans_out() -> None:
    """F33 + C50 + I48 patient at a single tick sees oncology + cardiology
    + psychiatry all fanned out."""
    patient = _profile(["F33", "C50.9", "I48"])
    tick = _specialty_fanout_tick(patient, datetime(2024, 3, 15))
    specialties = {s[0] for s in tick}
    assert {"oncology", "cardiology", "psychiatry"} <= specialties
