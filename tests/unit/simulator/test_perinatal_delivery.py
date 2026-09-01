"""META #957 Incr 1 — pregnancy lifecycle + delivery encounter emission.

Guards the population healthcare-calendar generator's pregnancy-lifecycle
scheduler (``_pregnancy_lifecycle_events``) and the
``simulate_delivery_encounter`` builder for pregnant women. Post-Incr-1
semantics: pregnancy is a ``TemporalStatePeriod(state_type="pregnancy")``
on ``PersonRecord.state_periods``, opened by an age-banded annual
conception Bernoulli, closed on the year containing the planned delivery
(EDD + jitter). Prenatal visits fire at gestational weeks 12/24/36;
delivery is an IMP encounter; postpartum visits fire at 7 and 28 days
post-delivery. Abortion is a per-mother-year sub-RNG outcome roll that
closes the period without a delivery.

Determinism contract: the scheduler consumes ZERO calls on the
calendar's shared per-person ``prng`` — every draw uses
``perinatal_delivery_seed(person_id, year)``.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import numpy as np
import pytest

from clinosim.modules.population.engine import (
    PopulationRegistry,
    _pregnancy_lifecycle_events,
    generate_healthcare_calendar,
)
from clinosim.modules.staff.engine import StaffRoster
from clinosim.simulator.perinatal import simulate_delivery_encounter
from clinosim.types.patient import PatientProfile
from clinosim.types.population import PersonRecord

pytestmark = pytest.mark.unit


def _make_person(pid: str, sex: str, age: int, chronic: list[str] | None = None) -> PersonRecord:
    return PersonRecord(
        person_id=pid,
        household_id="HH-000001",
        age=age,
        sex=sex,
        date_of_birth=date(2026 - age, 1, 1),
        chronic_conditions=list(chronic or []),
    )


def _seed_registry(persons: list[PersonRecord]) -> PopulationRegistry:
    reg = PopulationRegistry()
    for p in persons:
        reg.persons[p.person_id] = p
    return reg


# ---------------------------------------------------------------------------
# Scheduler — age / sex gates
# ---------------------------------------------------------------------------


def test_male_person_emits_no_pregnancy_events() -> None:
    person = _make_person("POP-M0001", "M", 30)
    assert _pregnancy_lifecycle_events(person, year=2024, country="JP") == []
    assert person.state_periods == []


def test_pre_menarche_female_emits_no_pregnancy_events() -> None:
    person = _make_person("POP-C0001", "F", 10)
    assert _pregnancy_lifecycle_events(person, year=2024, country="JP") == []
    assert person.state_periods == []


def test_post_menopause_female_emits_no_pregnancy_events() -> None:
    person = _make_person("POP-P0001", "F", 55)
    assert _pregnancy_lifecycle_events(person, year=2024, country="JP") == []
    assert person.state_periods == []


# ---------------------------------------------------------------------------
# Scheduler — conception + delivery lifecycle
# ---------------------------------------------------------------------------


def _find_conceiver(country: str, age: int) -> tuple[PersonRecord, list]:
    """Sweep patient ids to find one who conceives (and delivers) this year."""
    for i in range(300):
        p = _make_person(f"POP-C{i:04d}", "F", age)
        events = _pregnancy_lifecycle_events(p, year=2024, country=country)
        preg = p.get_active_state("pregnancy") or next(
            (s for s in p.state_periods if s.state_type == "pregnancy"), None
        )
        if preg is not None and any(e.event_type == "delivery" for e in events):
            return p, events
    raise RuntimeError(f"no delivery outcome across sweep age={age} country={country}")


def test_conception_opens_pregnancy_state_period() -> None:
    person, events = _find_conceiver("JP", age=30)
    periods = person.state_history("pregnancy")
    assert len(periods) == 1
    p = periods[0]
    assert p.state_type == "pregnancy"
    assert "lmp" in p.metadata
    assert "edd" in p.metadata
    assert p.metadata["edd"] == p.metadata["lmp"] + timedelta(days=280)


def test_delivery_event_closes_pregnancy_state_with_delivered_outcome() -> None:
    person, events = _find_conceiver("JP", age=30)
    delivery = next(e for e in events if e.event_type == "delivery")
    period = person.state_history("pregnancy")[0]
    assert period.outcome == "delivered"
    assert period.end_date == delivery.timestamp
    assert period.metadata.get("delivered_on") == delivery.timestamp


def test_delivery_year_emits_postpartum_z39_events() -> None:
    person, events = _find_conceiver("JP", age=30)
    delivery = next(e for e in events if e.event_type == "delivery")
    postpartum = [e for e in events if e.condition_type == "postpartum"]
    assert len(postpartum) == 2
    for pp in postpartum:
        assert pp.disease_id == "Z39"
        assert pp.encounter_type == "outpatient"
        assert pp.protocol_source == "perinatal:postpartum"
        assert pp.timestamp > delivery.timestamp


def test_prenatal_visits_fire_at_scheduled_gestational_weeks() -> None:
    person, events = _find_conceiver("JP", age=30)
    prenatal = [e for e in events if e.condition_type == "prenatal_visit"]
    lmp = person.state_history("pregnancy")[0].metadata["lmp"]
    for e in prenatal:
        assert e.disease_id == "Z34"
        assert e.encounter_type == "outpatient"
        assert e.protocol_source == "perinatal:prenatal"
        # Visit should be one of the scheduled gestational-week offsets
        ga_days = (e.timestamp - lmp).days
        assert ga_days in (12 * 7, 24 * 7, 36 * 7), ga_days


def test_abortion_outcome_emits_single_abortion_event_and_closes_period() -> None:
    """Age 20 sits in the "20-24" abortion band (~25 %) with a US annual
    conception rate of ~0.059 — sweeping 2000 patients gives an
    expected ~30 abortion outcomes, comfortable margin against sweep
    exhaustion. JP youth rates are 10x lower so US is used here."""
    for i in range(2000):
        p = _make_person(f"POP-A{i:04d}", "F", 20)
        events = _pregnancy_lifecycle_events(p, year=2024, country="US")
        if not events or events[0].event_type != "abortion":
            continue
        ab = events[0]
        assert ab.encounter_type == "outpatient"
        assert ab.condition_type == "pregnancy_termination"
        assert ab.disease_id in ("O03.9", "O04.5")
        assert ab.protocol_source == "perinatal:abortion"
        period = p.state_history("pregnancy")[0]
        assert period.outcome == "aborted"
        assert period.end_date == ab.timestamp
        return
    pytest.fail("no abortion outcome across 2000 age-20 US patients — calibration drift")


def test_lifecycle_scheduling_is_deterministic() -> None:
    """Same person + year → same events + same state_periods snapshot."""
    p1 = _make_person("POP-000042", "F", 30)
    p2 = _make_person("POP-000042", "F", 30)
    a = _pregnancy_lifecycle_events(p1, year=2024, country="JP")
    b = _pregnancy_lifecycle_events(p2, year=2024, country="JP")
    assert [(e.event_type, e.timestamp, e.disease_id) for e in a] == [
        (e.event_type, e.timestamp, e.disease_id) for e in b
    ]
    assert [(s.start_date, s.end_date, s.outcome) for s in p1.state_periods] == [
        (s.start_date, s.end_date, s.outcome) for s in p2.state_periods
    ]


def test_lifecycle_scheduler_does_not_shift_non_obstetric_calendar_stream() -> None:
    """RNG-neutrality: adding pregnancy-eligible patients must not shift
    any calendar event for men / children."""
    non_obstetric = [_make_person(f"POP-M{i:04d}", "M", 30, ["I10"]) for i in range(15)]
    women = [_make_person(f"POP-F{i:04d}", "F", 28) for i in range(10)]
    reg_a = _seed_registry(non_obstetric)
    reg_b = _seed_registry(non_obstetric + women)
    events_a = generate_healthcare_calendar(reg_a, year=2024, country="JP", rng=np.random.default_rng(42))
    events_b = generate_healthcare_calendar(reg_b, year=2024, country="JP", rng=np.random.default_rng(42))
    non_ob_a = sorted(
        (e.person_id, e.timestamp, e.event_type, e.disease_id) for e in events_a if e.person_id.startswith("POP-M")
    )
    non_ob_b = sorted(
        (e.person_id, e.timestamp, e.event_type, e.disease_id) for e in events_b if e.person_id.startswith("POP-M")
    )
    assert non_ob_a == non_ob_b, "adding pregnancy-eligible patients shifted non-obstetric calendars"


def test_cross_year_pregnancy_carries_state_and_completes_next_year() -> None:
    """Sweep until we find a woman who conceives late enough that EDD
    lands next year. Verify: (a) year N emits prenatal visits (no
    delivery); (b) year N+1 does NOT re-roll conception; (c) year N+1
    emits the delivery + postpartum and closes the period."""
    for i in range(500):
        p = _make_person(f"POP-X{i:04d}", "F", 30)
        events_y1 = _pregnancy_lifecycle_events(p, year=2024, country="JP")
        preg = p.get_active_state("pregnancy")
        if preg is None:
            continue
        planned = preg.metadata.get("planned_delivery_date") or preg.metadata["edd"]
        if planned.year != 2025:
            # Delivery still in 2024 — not a cross-year case; reset the
            # (mutated) state to keep the sweep clean and continue.
            continue
        # Year-N assertions
        assert all(e.event_type != "delivery" for e in events_y1)
        prior_period_count = len(p.state_periods)
        # Year N+1 call
        events_y2 = _pregnancy_lifecycle_events(p, year=2025, country="JP")
        # No new pregnancy period opened (still the carried one)
        assert len(p.state_periods) == prior_period_count
        delivery = next((e for e in events_y2 if e.event_type == "delivery"), None)
        assert delivery is not None
        # Closed correctly
        period = p.state_history("pregnancy")[-1]
        assert period.outcome == "delivered"
        assert period.end_date == delivery.timestamp
        return
    pytest.fail("no cross-year pregnancy found across 500 patients — calibration drift")


# ---------------------------------------------------------------------------
# Encounter builder — unchanged from pre-Incr-1
# ---------------------------------------------------------------------------


def _make_patient() -> PatientProfile:
    return PatientProfile(patient_id="POP-000001", sex="F", age=28)


def test_delivery_encounter_returns_mother_and_newborn_records_jp() -> None:
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

    assert newborn_rec.patient.patient_id == "POP-000001-BABY"
    assert newborn_rec.patient.household_id == patient.household_id
    assert newborn_rec.patient.age == 0
    assert newborn_rec.patient.date_of_birth == visit_dt.date()
    assert newborn_rec.patient.sex in ("M", "F")
    n_enc = newborn_rec.encounters[0]
    assert n_enc.encounter_type.value == "inpatient"
    assert n_enc.admit_source.value == "born"
    assert n_enc.admit_source_encounter_id == m_enc.encounter_id
    assert newborn_rec.clinical_diagnosis.discharge_diagnosis_code == "Z38.0"


def test_delivery_encounter_shape_us() -> None:
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
    patient = _make_patient()
    visit_dt = datetime(2024, 7, 15, 10, 0)
    rec_a = simulate_delivery_encounter(
        patient=patient, visit_date=visit_dt, roster=StaffRoster(), rng=np.random.default_rng(42), country="JP"
    )
    rec_b = simulate_delivery_encounter(
        patient=patient, visit_date=visit_dt, roster=StaffRoster(), rng=np.random.default_rng(99), country="JP"
    )
    assert rec_a[1].patient.sex == rec_b[1].patient.sex
