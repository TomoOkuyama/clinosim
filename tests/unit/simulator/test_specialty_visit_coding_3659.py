"""Issue #3659: a specialty follow-up is coded with the condition that routed the patient to it."""

from __future__ import annotations

from datetime import date, datetime
from types import SimpleNamespace

import numpy as np
import pytest

from clinosim import determinism
from clinosim.locale.loader import load_demographics, load_specialty_routing
from clinosim.modules.patient.activator import activate_patient
from clinosim.modules.population.engine import PersonRecord
from clinosim.modules.staff.engine import StaffRoster
from clinosim.simulator.outpatient import _simulate_outpatient_visit, _specialty_fanout_tick
from clinosim.types.patient import ChronicCondition, PatientProfile

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _clear() -> None:
    load_specialty_routing.cache_clear()
    yield
    load_specialty_routing.cache_clear()


def _profile(codes: list[str]) -> PatientProfile:
    p = PatientProfile(patient_id="pt-3659", age=60, sex="F", date_of_birth=date(1966, 1, 1))
    p.chronic_conditions = [ChronicCondition(code=c, system="icd-10-cm") for c in codes]
    return p


def _by_specialty(codes: list[str]) -> dict[str, str]:
    ticks = _specialty_fanout_tick(_profile(codes), datetime(2025, 3, 3))
    return {t.specialty: t.chronic_code for t in ticks}


def test_psychiatry_tick_names_the_psychiatric_code_not_the_other_condition() -> None:
    assert _by_specialty(["M81", "F41.1"]) == {"psychiatry": "F41.1"}


@pytest.mark.parametrize("code", ["I48", "I50", "I25"])
def test_cardiology_tick_names_the_cardiac_code(code: str) -> None:
    assert _by_specialty(["E78", code, "I10"]) == {"cardiology": code}


def test_oncology_tick_names_the_cancer_and_is_single_for_two_cancers() -> None:
    ticks = _specialty_fanout_tick(_profile(["I10", "C50.9", "C18.9"]), datetime(2025, 3, 3))
    assert [(t.specialty, t.chronic_code) for t in ticks] == [("oncology", "C50.9")]


def test_pulmonology_and_each_psychiatric_route() -> None:
    assert _by_specialty(["J44"]) == {"pulmonology": "J44"}
    for code in ("F32", "F33", "F20", "F31"):
        assert _by_specialty([code]) == {"psychiatry": code}


def test_tick_is_still_a_specialty_cadence_period_tuple() -> None:
    tick = _specialty_fanout_tick(_profile(["F32"]), datetime(2025, 5, 1))[0]
    assert tick[:3] == ("psychiatry", "quarterly", (2025, 2))


@pytest.mark.parametrize("code", ["F41.1", "I48", "C50.9", "J44"])
def test_visit_with_the_routing_code_is_coded_with_it(code: str) -> None:
    person = PersonRecord(person_id="T-3659", household_id="H", age=60, sex="F", date_of_birth=date(1966, 1, 1))
    patient = activate_patient(person, determinism.default_rng(3), load_demographics("US"))
    record = _simulate_outpatient_visit(
        patient,
        "chronic_followup",
        datetime(2025, 5, 12, 10, 0),
        StaffRoster(),
        np.random.default_rng(3),
        chronic_code=code,
        followup_spec={"labs": [], "visit_reason": {"en": "Specialty follow-up", "ja": "専門外来"}},
        country="US",
    )
    assert record.clinical_diagnosis.admission_diagnosis_code.startswith(code[:3])


def test_calendar_passes_the_routing_code_to_the_specialty_visit(monkeypatch: pytest.MonkeyPatch) -> None:
    import clinosim.modules.monitoring as monitoring
    import clinosim.simulator.hospital_ops as hospital_ops
    import clinosim.simulator.outpatient as outpatient
    from clinosim.modules.population.engine import LifeEvent
    from clinosim.simulator._dispatch import InpatientStayIndex
    from clinosim.simulator.outpatient import SpecialtyTick
    from clinosim.simulator.phases import _healthcare_calendar as hc

    person = SimpleNamespace(in_population_at=lambda _d: True)
    ctx = SimpleNamespace(
        population=SimpleNamespace(get_person=lambda _pid: person),
        patient_records=[],
        patient_cache={},
        master_seed=1,
        demo={},
        roster=None,
        hospital_ops={},
        config=SimpleNamespace(country="US"),
        followup_data={},
        outpatient_day_ends={},
        inpatient_stays=InpatientStayIndex(),
    )
    calls: list[str] = []

    def _visit(*_a, **kw):
        calls.append(kw.get("chronic_code", ""))
        return SimpleNamespace(encounters=[])

    monkeypatch.setattr(
        hc, "_activate_cached_person", lambda person, **_k: SimpleNamespace(patient_id="P1", current_medications=[])
    )
    monkeypatch.setattr(hc, "_simulate_outpatient_visit", _visit)
    monkeypatch.setattr(hc, "resolve_outpatient_department", lambda *_a, **_k: "internal_medicine")
    monkeypatch.setattr(monitoring, "monitoring_labs_for_patient", lambda *_a, **_k: [])
    monkeypatch.setattr(
        outpatient, "_specialty_fanout_tick", lambda *_a: [SpecialtyTick("cardiology", "semi_annual", (2025, 2), "I48")]
    )
    monkeypatch.setattr(hospital_ops, "resolve_department", lambda name, _ops: name)
    event = LifeEvent(person_id="P1", event_type="chronic_visit", timestamp=date(2025, 11, 3), disease_id="E78")
    hc.dispatch_calendar_event(event, ctx)
    assert calls == ["E78", "I48"]
