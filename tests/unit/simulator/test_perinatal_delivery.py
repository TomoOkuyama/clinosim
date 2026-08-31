"""Issue #957 Tier-3-B — perinatal delivery encounter emission.

Guards the population healthcare-calendar generator's ``delivery`` event
scheduler + the ``simulate_delivery_encounter`` builder for Z34-carrying
pregnant women. Slice-1 scope: mother-side inpatient encounter with
admission dx O80 (single spontaneous delivery), discharge dx Z37.0
(single liveborn — mother-side birth outcome, sex-locked female-only),
and one delivery Procedure. Newborn Patient + postpartum + Z38 are
follow-up slices.

Determinism contract: the scheduler consumes ZERO calls on the
calendar's shared per-person ``prng``; the delivery month/day are
drawn from ``perinatal_delivery_seed(person_id, year)``.
"""

from __future__ import annotations

from datetime import date, datetime

import numpy as np
import pytest

from clinosim.modules.population.engine import (
    PopulationRegistry,
    _perinatal_delivery_events,
    generate_healthcare_calendar,
)
from clinosim.modules.staff.engine import StaffRoster
from clinosim.simulator.perinatal import simulate_delivery_encounter
from clinosim.types.patient import PatientProfile
from clinosim.types.population import PersonRecord

pytestmark = pytest.mark.unit


def _make_person(pid: str, sex: str, age: int, chronic: list[str]) -> PersonRecord:
    return PersonRecord(
        person_id=pid,
        household_id="HH-000001",
        age=age,
        sex=sex,
        date_of_birth=date(2026 - age, 1, 1),
        chronic_conditions=list(chronic),
    )


def _seed_registry(persons: list[PersonRecord]) -> PopulationRegistry:
    reg = PopulationRegistry()
    for p in persons:
        reg.persons[p.person_id] = p
    return reg


# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------


def test_person_without_z34_emits_no_delivery_event() -> None:
    """A patient without the Z34 chronic marker (not actively pregnant
    in the sim window) produces zero delivery events."""
    person = _make_person("POP-000001", "F", 30, ["I10", "E11.9"])
    assert _perinatal_delivery_events(person, year=2024) == []


def test_person_with_z34_emits_exactly_one_delivery_event_per_year() -> None:
    """A Z34-carrying woman emits exactly ONE delivery event per year
    (slice-1: one delivery per pregnancy-year; multi-year pregnancies
    are folded into a single-year event for MVP simplicity)."""
    person = _make_person("POP-000001", "F", 28, ["Z34"])
    events = _perinatal_delivery_events(person, year=2024)
    assert len(events) == 1
    ev = events[0]
    assert ev.event_type == "delivery"
    assert ev.disease_id == "Z34"
    assert ev.condition_type == "perinatal_delivery"
    assert ev.encounter_type == "inpatient"
    assert ev.timestamp.year == 2024


def test_delivery_month_falls_in_config_window() -> None:
    """Delivery month must land inside the ``delivery_month_range`` from
    ``perinatal.yaml`` (default [4, 10])."""
    for i in range(50):
        person = _make_person(f"POP-{i:06d}", "F", 28, ["Z34"])
        events = _perinatal_delivery_events(person, year=2024)
        assert len(events) == 1
        assert 4 <= events[0].timestamp.month <= 10, events[0].timestamp


def test_delivery_scheduling_is_deterministic() -> None:
    """Same person + year always picks the same delivery date."""
    person = _make_person("POP-000042", "F", 30, ["Z34"])
    a = _perinatal_delivery_events(person, year=2024)
    b = _perinatal_delivery_events(person, year=2024)
    assert a[0].timestamp == b[0].timestamp


def test_delivery_scheduler_does_not_shift_non_z34_calendar_stream() -> None:
    """RNG-neutrality: adding Z34 patients to a cohort must not shift
    any calendar event for non-Z34 patients."""
    non_z34 = [_make_person(f"POP-N{i:04d}", "F", 30, ["I10"]) for i in range(15)]
    z34_slice = [_make_person(f"POP-Z{i:04d}", "F", 28, ["Z34"]) for i in range(10)]
    reg_a = _seed_registry(non_z34)
    reg_b = _seed_registry(non_z34 + z34_slice)
    events_a = generate_healthcare_calendar(reg_a, year=2024, country="JP", rng=np.random.default_rng(42))
    events_b = generate_healthcare_calendar(reg_b, year=2024, country="JP", rng=np.random.default_rng(42))
    non_z34_a = sorted(
        (e.person_id, e.timestamp, e.event_type, e.disease_id) for e in events_a if e.person_id.startswith("POP-N")
    )
    non_z34_b = sorted(
        (e.person_id, e.timestamp, e.event_type, e.disease_id) for e in events_b if e.person_id.startswith("POP-N")
    )
    assert non_z34_a == non_z34_b, "adding Z34 patients shifted non-Z34 calendar streams"


# ---------------------------------------------------------------------------
# Encounter builder
# ---------------------------------------------------------------------------


def _make_patient() -> PatientProfile:
    return PatientProfile(patient_id="POP-000001", sex="F", age=28)


def test_delivery_encounter_shape_jp() -> None:
    """JP delivery encounter: inpatient, LOS=5 days, admission dx O80,
    discharge dx Z37.0, Procedure with K894 (JP MHLW) primary code."""
    patient = _make_patient()
    visit_dt = datetime(2024, 7, 15, 10, 0)
    record = simulate_delivery_encounter(
        patient=patient,
        visit_date=visit_dt,
        roster=StaffRoster(),
        rng=np.random.default_rng(42),
        country="JP",
        hospital_ops={},
    )
    assert len(record.encounters) == 1
    enc = record.encounters[0]
    assert enc.encounter_type.value == "inpatient"
    assert enc.admission_datetime == visit_dt
    assert (enc.discharge_datetime - visit_dt).days == 5, "JP delivery LOS should be 5 days"
    assert record.clinical_diagnosis.admission_diagnosis_code == "O80"
    assert record.clinical_diagnosis.discharge_diagnosis_code == "Z37.0"
    assert len(record.procedures) == 1
    proc = record.procedures[0]
    assert proc.procedure_type == "delivery"
    assert proc.procedure_code == "K894"
    assert proc.procedure_code_jp == "K894"


def test_delivery_encounter_shape_us() -> None:
    """US delivery encounter: inpatient, LOS=2 days, admission dx O80,
    discharge dx Z37.0, Procedure with 59400 (CPT) primary code."""
    patient = _make_patient()
    visit_dt = datetime(2024, 7, 15, 10, 0)
    record = simulate_delivery_encounter(
        patient=patient,
        visit_date=visit_dt,
        roster=StaffRoster(),
        rng=np.random.default_rng(42),
        country="US",
        hospital_ops={},
    )
    enc = record.encounters[0]
    assert (enc.discharge_datetime - visit_dt).days == 2, "US delivery LOS should be 2 days"
    proc = record.procedures[0]
    assert proc.procedure_code == "59400"
    assert proc.procedure_code_us == "59400"
