"""A delivery admission records the mother's vital signs (Issue #3007).

Every delivery stay had no blood pressure, pulse or temperature, and the
nursing notes read 'no vital record'. Intrapartum / postpartum vitals are
taken frequently over the first 24 hours (more often after a cesarean) and
once per nursing shift afterwards (perinatal.yaml ``maternal_vitals``).
"""

from __future__ import annotations

from datetime import datetime

import numpy as np
import pytest

from clinosim.locale.loader import load_perinatal_config
from clinosim.modules.staff.engine import StaffRoster
from clinosim.simulator.perinatal import simulate_delivery_encounter
from clinosim.types.patient import PatientProfile

pytestmark = pytest.mark.unit

_ADMIT = datetime(2025, 7, 15, 10, 0)


def _mother_record(patient_id: str, country: str):
    patient = PatientProfile(patient_id=patient_id, sex="F", age=30)
    records = simulate_delivery_encounter(
        patient=patient,
        visit_date=_ADMIT,
        roster=StaffRoster(),
        rng=np.random.default_rng(1),
        country=country,
        hospital_ops={},
    )
    return records[0]


def _cesarean_mother(country: str):
    for i in range(400):
        rec = _mother_record(f"POP-{i:06d}", country)
        if rec.clinical_diagnosis.admission_diagnosis_code == "O82":
            return rec
    pytest.fail("no cesarean delivery in 400 mothers")


def _vaginal_mother(country: str):
    for i in range(400):
        rec = _mother_record(f"POP-{i:06d}", country)
        if not rec.clinical_diagnosis.admission_diagnosis_code == "O82":
            return rec
    pytest.fail("no vaginal delivery in 400 mothers")


def _full_sets_by_day(rec) -> dict[int, int]:
    enc = rec.encounters[0]
    out: dict[int, int] = {}
    for v in rec.vital_signs:
        assert enc.admission_datetime <= v.timestamp < enc.discharge_datetime
        if v.systolic_bp and v.heart_rate and v.temperature_celsius:
            day = (v.timestamp.date() - enc.admission_datetime.date()).days
            out[day] = out.get(day, 0) + 1
    return out


@pytest.mark.parametrize("country", ["JP", "US"])
def test_a_cesarean_admission_produces_daily_vitals(country: str) -> None:
    rec = _cesarean_mother(country)
    enc = rec.encounters[0]
    by_day = _full_sets_by_day(rec)
    stay_days = (enc.discharge_datetime.date() - enc.admission_datetime.date()).days
    assert set(range(stay_days)) <= set(by_day), by_day
    first_24h = [v for v in rec.vital_signs if (v.timestamp - enc.admission_datetime).total_seconds() < 86400]
    assert len(first_24h) == len(load_perinatal_config()["maternal_vitals"]["first_day_offsets_hours"]["cesarean"])


@pytest.mark.parametrize("country", ["JP", "US"])
def test_a_vaginal_delivery_has_vitals_every_day_and_fewer_on_the_first(country: str) -> None:
    rec = _vaginal_mother(country)
    enc = rec.encounters[0]
    stay_days = (enc.discharge_datetime.date() - enc.admission_datetime.date()).days
    assert set(range(stay_days)) <= set(_full_sets_by_day(rec))
    cfg = load_perinatal_config()["maternal_vitals"]["first_day_offsets_hours"]
    assert len(cfg["vaginal"]) < len(cfg["cesarean"])


def test_maternal_vitals_are_plausible_and_deterministic() -> None:
    a = _mother_record("POP-000042", "JP")
    b = _mother_record("POP-000042", "JP")
    assert [(v.timestamp, v.systolic_bp, v.heart_rate) for v in a.vital_signs] == [
        (v.timestamp, v.systolic_bp, v.heart_rate) for v in b.vital_signs
    ]
    for v in a.vital_signs:
        assert 85 <= v.systolic_bp <= 160 and 50 <= v.heart_rate <= 130
        assert 35.0 <= v.temperature_celsius <= 38.5
