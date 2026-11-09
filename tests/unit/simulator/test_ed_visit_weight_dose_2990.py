"""A child's ED dose follows the weight charted at the visit (Issue #2990).

The dose was computed from the registration-time profile weight, so a
child who had grown since registration got 20-30 mg/kg of acetaminophen.
The weight now comes from the same growth-curve derivation as the
encounter's body-weight Observation.
"""

from __future__ import annotations

import dataclasses
from datetime import date, datetime
from types import SimpleNamespace

import pytest

from clinosim.modules.output.fhir_r4.labs.anthropometrics import (
    LOINC_BODY_WEIGHT,
    build_anthropometric_observations,
)
from clinosim.modules.population.encounter_anthropometry import encounter_weight_kg
from clinosim.simulator.emergency import ed_pediatric_dose_name
from clinosim.types.patient import PatientProfile

pytestmark = pytest.mark.unit


def _toddler() -> PatientProfile:
    # Registered as an infant (6.2 kg); 2 years 3 months old at the visit.
    return PatientProfile(
        patient_id="POP-002995", sex="M", date_of_birth=date(2023, 6, 1), age=0, height_cm=62.0, weight_kg=6.2
    )


def _visit() -> SimpleNamespace:
    return SimpleNamespace(encounter_id="ENC-002990-ED", admission_datetime=datetime(2025, 9, 1, 10, 30))


def _charted_weight(patient: PatientProfile, visit: SimpleNamespace, country: str) -> float:
    enc = {"encounter_id": visit.encounter_id, "admission_datetime": visit.admission_datetime}
    # The FHIR builder reads the CIF patient dict (date of birth as an ISO string).
    cif_patient = {**dataclasses.asdict(patient), "date_of_birth": patient.date_of_birth.isoformat()}
    obs = build_anthropometric_observations(cif_patient, enc, country)
    return next(o["valueQuantity"]["value"] for o in obs if o["code"]["coding"][0]["code"] == LOINC_BODY_WEIGHT)


@pytest.mark.parametrize("country", ["US", "JP"])
def test_visit_weight_is_the_charted_body_weight(country: str) -> None:
    patient, visit = _toddler(), _visit()
    weight = encounter_weight_kg(patient, visit.encounter_id, visit.admission_datetime, country)
    assert weight == _charted_weight(patient, visit, country)


def test_two_year_old_seen_at_12_kg_gets_120_to_180_mg() -> None:
    patient, visit = _toddler(), _visit()
    charted = _charted_weight(patient, visit, "US")
    assert charted == 12.0
    name = ed_pediatric_dose_name("Acetaminophen 500mg", patient, visit, visit.admission_datetime, "US")
    assert name is not None
    mg = float(name.split()[1].removesuffix("mg"))
    assert 120 <= mg <= 180
    assert 10.0 <= mg / charted <= 15.0


def test_adult_dose_is_unchanged() -> None:
    adult = PatientProfile(patient_id="POP-A", sex="F", date_of_birth=date(1980, 1, 1), age=45, weight_kg=60.0)
    visit = _visit()
    assert (
        ed_pediatric_dose_name("Acetaminophen 500mg", adult, visit, visit.admission_datetime, "US")
        == "Acetaminophen 500mg"
    )
