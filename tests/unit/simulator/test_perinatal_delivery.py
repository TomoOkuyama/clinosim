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


def test_z34_delivery_outcome_emits_delivery_plus_two_postpartum_events() -> None:
    """A Z34-carrying woman whose per-mother outcome roll picks
    ``delivery`` (majority path) emits ONE ``delivery`` event + TWO
    ``chronic_visit`` postpartum events per pregnancy-year (Slice 2:
    JSOG / ACOG standard 1-week + 4-week post-delivery follow-ups)."""
    # Age 40 sits in the "35-44" bin with the lowest abortion rate
    # (~7 %), so most patients in this band go through the delivery
    # path. Sweep patient ids until we hit one.
    for i in range(200):
        person = _make_person(f"POP-DL{i:04d}", "F", 40, ["Z34"])
        events = _perinatal_delivery_events(person, year=2024)
        if events[0].event_type != "delivery":
            continue  # rolled abortion for this patient — try another
        assert len(events) == 3
        assert events[0].disease_id == "Z34"
        assert events[0].condition_type == "perinatal_delivery"
        assert events[0].encounter_type == "inpatient"
        for pp in events[1:]:
            assert pp.event_type == "chronic_visit"
            assert pp.condition_type == "postpartum"
            assert pp.disease_id == "Z39"
            assert pp.encounter_type == "outpatient"
            assert pp.protocol_source == "perinatal:postpartum"
        assert events[1].timestamp > events[0].timestamp
        assert events[2].timestamp > events[1].timestamp
        return
    pytest.fail("no delivery outcome observed across 200 age-40 Z34 patients — abortion rate calibration drift")


def test_z34_abortion_outcome_emits_single_abortion_event() -> None:
    """A Z34-carrying woman whose per-mother outcome roll picks
    ``abortion`` (age-gated minority path) emits ONE ``abortion``
    event, no delivery, no postpartum. Discharge dx is O03.9
    (spontaneous) or O04.5 (induced) per the induced-share split."""
    # Age 17 sits in the "15-19" bin with the highest abortion rate
    # (40 %), so a sweep hits abortion outcomes quickly.
    for i in range(50):
        person = _make_person(f"POP-AB{i:04d}", "F", 17, ["Z34"])
        events = _perinatal_delivery_events(person, year=2024)
        if events[0].event_type != "abortion":
            continue
        assert len(events) == 1
        ab = events[0]
        assert ab.encounter_type == "outpatient"
        assert ab.condition_type == "pregnancy_termination"
        assert ab.disease_id in ("O03.9", "O04.5")
        assert ab.protocol_source == "perinatal:abortion"
        return
    pytest.fail("no abortion outcome across 50 age-17 Z34 patients — abortion rate calibration drift")


def test_delivery_month_falls_in_config_window() -> None:
    """Delivery month must land inside the ``delivery_month_range`` from
    ``perinatal.yaml`` (default [4, 10]). Applies to both delivery
    AND abortion events since both share the scheduled date draw."""
    for i in range(50):
        person = _make_person(f"POP-{i:06d}", "F", 40, ["Z34"])
        events = _perinatal_delivery_events(person, year=2024)
        head = events[0]
        assert 4 <= head.timestamp.month <= 10, head.timestamp


def test_delivery_scheduling_is_deterministic() -> None:
    """Same person + year always picks the same delivery + postpartum
    dates."""
    person = _make_person("POP-000042", "F", 30, ["Z34"])
    a = _perinatal_delivery_events(person, year=2024)
    b = _perinatal_delivery_events(person, year=2024)
    assert [(e.event_type, e.timestamp) for e in a] == [(e.event_type, e.timestamp) for e in b]


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


def test_delivery_encounter_returns_mother_and_newborn_records_jp() -> None:
    """JP delivery: mother's IMP encounter (LOS=5d, O80/Z37.0, K894
    Procedure) + newborn's IMP encounter (admitSource=born, partOf →
    mother's encounter, Z38.0)."""
    patient = _make_patient()
    visit_dt = datetime(2024, 7, 15, 10, 0)
    records = simulate_delivery_encounter(
        patient=patient,
        visit_date=visit_dt,
        roster=StaffRoster(),
        rng=np.random.default_rng(42),
        country="JP",
        hospital_ops={},
    )
    assert len(records) == 2, "delivery must return mother + newborn records"
    mother_rec, newborn_rec = records

    # Mother-side
    assert mother_rec.patient.patient_id == "POP-000001"
    m_enc = mother_rec.encounters[0]
    assert m_enc.encounter_type.value == "inpatient"
    assert m_enc.admission_datetime == visit_dt
    assert (m_enc.discharge_datetime - visit_dt).days == 5, "JP delivery LOS should be 5 days"
    assert mother_rec.clinical_diagnosis.admission_diagnosis_code == "O80"
    assert mother_rec.clinical_diagnosis.discharge_diagnosis_code == "Z37.0"
    assert len(mother_rec.procedures) == 1
    assert mother_rec.procedures[0].procedure_code == "K894"
    assert mother_rec.procedures[0].procedure_type == "delivery"

    # Newborn-side (Slice 2)
    assert newborn_rec.patient.patient_id == "POP-000001-BABY"
    assert newborn_rec.patient.household_id == patient.household_id
    assert newborn_rec.patient.age == 0
    assert newborn_rec.patient.date_of_birth == visit_dt.date()
    assert newborn_rec.patient.sex in ("M", "F")
    n_enc = newborn_rec.encounters[0]
    assert n_enc.encounter_type.value == "inpatient"
    assert n_enc.admit_source.value == "born"
    # FHIR mother→baby link
    assert n_enc.admit_source_encounter_id == m_enc.encounter_id
    assert newborn_rec.clinical_diagnosis.discharge_diagnosis_code == "Z38.0"


def test_delivery_encounter_shape_us() -> None:
    """US delivery: LOS=2d, mother has 59400 CPT Procedure, newborn
    still has Z38.0 discharge dx + partOf link to mother."""
    patient = _make_patient()
    visit_dt = datetime(2024, 7, 15, 10, 0)
    records = simulate_delivery_encounter(
        patient=patient,
        visit_date=visit_dt,
        roster=StaffRoster(),
        rng=np.random.default_rng(42),
        country="US",
        hospital_ops={},
    )
    assert len(records) == 2
    mother_rec, newborn_rec = records
    m_enc = mother_rec.encounters[0]
    assert (m_enc.discharge_datetime - visit_dt).days == 2, "US delivery LOS should be 2 days"
    assert mother_rec.procedures[0].procedure_code == "59400"
    assert newborn_rec.encounters[0].admit_source_encounter_id == m_enc.encounter_id
    assert newborn_rec.clinical_diagnosis.discharge_diagnosis_code == "Z38.0"


def test_newborn_sex_is_deterministic_per_mother() -> None:
    """Same mother → same newborn sex across independent simulate
    calls (per-mother sub-RNG isolation)."""
    patient = _make_patient()
    visit_dt = datetime(2024, 7, 15, 10, 0)
    rec_a = simulate_delivery_encounter(
        patient=patient, visit_date=visit_dt, roster=StaffRoster(), rng=np.random.default_rng(42), country="JP"
    )
    rec_b = simulate_delivery_encounter(
        patient=patient, visit_date=visit_dt, roster=StaffRoster(), rng=np.random.default_rng(99), country="JP"
    )
    # Different mother-side rng but the same newborn sex — proves
    # newborn sex is derived from mother_id (per-mother sub-RNG),
    # not from the caller's rng.
    assert rec_a[1].patient.sex == rec_b[1].patient.sex
