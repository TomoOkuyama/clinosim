"""The newborn profile's weight and length are the baby's own birth
measurements, the values of its birth-day Observations (Issue #3667)."""

from __future__ import annotations

from datetime import datetime

import numpy as np
import pytest

from clinosim.modules.population.encounter_anthropometry import encounter_anthropometrics
from clinosim.modules.staff.engine import StaffRoster
from clinosim.simulator.perinatal import simulate_delivery_encounter
from clinosim.types.patient import PatientProfile

pytestmark = pytest.mark.unit


def _baby(i: int, country: str):
    return simulate_delivery_encounter(
        patient=PatientProfile(patient_id=f"POP-{i:06d}", sex="F", age=30),
        visit_date=datetime(2025, 7, 15, 10, 0),
        roster=StaffRoster(),
        rng=np.random.default_rng(1),
        country=country,
        hospital_ops={},
    )[1]


@pytest.mark.parametrize("country", ["US", "JP"])
def test_profile_weight_and_length_equal_the_birth_day_measurements(country: str) -> None:
    weights = set()
    for i in range(1, 40):
        baby = _baby(i, country)
        enc = baby.encounters[0]
        charted = encounter_anthropometrics(baby.patient, enc.encounter_id, enc.admission_datetime, country)
        assert baby.patient.weight_kg == charted["weight_kg"]
        assert baby.patient.height_cm == charted["height_cm"]
        assert baby.patient.bmi == charted["bmi"]
        weights.add(baby.patient.weight_kg)
    assert len(weights) > 8 and 2.0 < min(weights) and max(weights) < 5.0
