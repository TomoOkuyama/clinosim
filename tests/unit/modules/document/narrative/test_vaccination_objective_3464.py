"""Issue #3464: a vaccination visit's objective records the pre-vaccination
check (temperature and pulse) and a child's growth, instead of "no findings"."""

from __future__ import annotations

import re
from datetime import date, datetime

import pytest

from clinosim import determinism
from clinosim.locale.loader import load_demographics, visit_vitals
from clinosim.modules.immunization.enricher import _synthesize_vaccination_encounter, _synthesize_vaccination_vitals
from clinosim.modules.patient.activator import activate_patient
from clinosim.modules.population.engine import PersonRecord
from tests.unit.modules.document.narrative.test_visit_reason_soap_3249 import _imm, _record, _soap

pytestmark = pytest.mark.unit


def _vax_record(country: str, dob: date, vitals: dict | None, when: str, cvx: str, dx: str = "Z23") -> dict:
    imm = {**_imm(cvx, None, "L1"), "occurrence_date": when[:10]}
    record = _record(
        country=country,
        visit_type="",
        condition="",
        dx=dx,
        chronic=[],
        age_dob=dob,
        when=when,
        immunizations=[imm],
        vitals=vitals,
    )
    if vitals is None:
        record["vital_signs"] = []
    return record


@pytest.mark.parametrize("country", ["US", "JP"])
def test_infant_vaccination_objective_has_temperature_and_growth(country: str) -> None:
    record = _vax_record(
        country, date(2026, 1, 10), {"temperature_celsius": 36.6, "heart_rate": 120}, "2026-03-23T10:00:00", "10"
    )
    objective = _soap(record, country)["O"]
    assert "36.6" in objective
    assert ("体重" if country == "JP" else "Body weight") in objective
    assert "特記事項なし" not in objective and "No significant" not in objective


def test_adult_vaccination_objective_has_temperature() -> None:
    record = _vax_record(
        "JP",
        date(1955, 1, 1),
        {"temperature_celsius": 36.4, "heart_rate": 70, "systolic_bp": 120, "diastolic_bp": 70},
        "2026-10-20T10:00:00",
        "140",
    )
    objective = _soap(record, "JP")["O"]
    assert "36.4" in objective


def test_no_vital_means_no_invented_temperature() -> None:
    record = _vax_record("US", date(2026, 1, 10), None, "2026-03-23T10:00:00", "10")
    objective = _soap(record, "US")["O"]
    assert not re.search(r"temp", objective, re.IGNORECASE)
    assert "Body weight" in objective


def test_visit_vitals_table() -> None:
    assert visit_vitals("flu_vaccination") == {"temp", "hr", "bp"}
    assert visit_vitals("vaccination_child") == {"temp", "hr"}
    assert visit_vitals("no_such_visit") is None


def _patient(dob: date):
    person = PersonRecord(person_id="T-3464", household_id="H-1", age=2026 - dob.year, sex="F", date_of_birth=dob)
    return activate_patient(person, determinism.default_rng(5), load_demographics("US"))


def test_companion_visit_vitals_are_deterministic_and_typed() -> None:
    from clinosim.types.encounter import ImmunizationRecord

    for dob, bp in ((date(2026, 1, 10), False), (date(1950, 1, 1), True)):
        patient = _patient(dob)
        imm = ImmunizationRecord(vaccine_cvx="140", occurrence_date=date(2026, 10, 20))
        enc = _synthesize_vaccination_encounter(imm, patient.patient_id, "US")
        a = _synthesize_vaccination_vitals(patient, enc, 42, "N1")
        b = _synthesize_vaccination_vitals(patient, enc, 42, "N1")
        assert a == b and a is not None
        assert a.temperature_celsius is not None and a.heart_rate is not None
        assert (a.systolic_bp is not None) is bp
        assert a.timestamp == enc.admission_datetime and a.measured_by == "N1"
        assert isinstance(a.timestamp, datetime)


def test_stub_patient_without_physiology_gets_no_vitals() -> None:
    from types import SimpleNamespace

    from clinosim.types.encounter import ImmunizationRecord

    imm = ImmunizationRecord(vaccine_cvx="140", occurrence_date=date(2026, 10, 20))
    enc = _synthesize_vaccination_encounter(imm, "p", "US")
    assert _synthesize_vaccination_vitals(SimpleNamespace(patient_id="p"), enc, 1) is None


def test_hosting_encounter_does_not_see_the_companion_visit_vitals() -> None:
    from clinosim.modules.document.narrative.passes import scope_record_to_encounter

    own = {
        "encounter_id": "ENC-A",
        "admission_datetime": "2024-01-04T10:00:00",
        "discharge_datetime": "2024-01-04T10:20:00",
    }
    vax = {
        "encounter_id": "ENC-VAX-1",
        "admission_datetime": "2024-10-01T10:00:00",
        "discharge_datetime": "2024-10-01T10:00:00",
    }
    record = {
        "encounters": [own, vax],
        "vital_signs": [{"timestamp": "2024-01-04T10:05:00"}, {"timestamp": "2024-10-01T10:00:00"}],
    }
    assert [v["timestamp"] for v in scope_record_to_encounter(record, own)["vital_signs"]] == ["2024-01-04T10:05:00"]
    assert [v["timestamp"] for v in scope_record_to_encounter(record, vax)["vital_signs"]] == ["2024-10-01T10:00:00"]
    only_own = {"encounters": [own], "vital_signs": record["vital_signs"][:1]}
    assert scope_record_to_encounter(only_own, own) is only_own
