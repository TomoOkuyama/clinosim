"""Issue #3357: newborn-screen and type-and-screen reports name their performer."""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from clinosim.modules.newborn import enrich_newborn
from clinosim.modules.newborn.fhir_emit import (
    _bb_newborn_metabolic_screen_diagnostic_report,
    _bb_newborn_metabolic_screen_observation,
    _bb_newborn_screening_laboratory,
)
from clinosim.modules.output.fhir_r4.labs.blood_type import _bb_blood_type
from clinosim.types.clinical import ConditionEvent
from clinosim.types.encounter import Encounter, EncounterType
from clinosim.types.output import CIFPatientRecord
from clinosim.types.patient import PatientProfile

pytestmark = pytest.mark.unit


def _newborn(country: str, n: int = 1) -> SimpleNamespace:
    pid = f"POP-00000{n}-BABY"
    admit = datetime(2026, 6, 1, 10, 0)
    enc = Encounter(
        encounter_id=f"ENC-{pid}-01",
        patient_id=pid,
        encounter_type=EncounterType.INPATIENT,
        admission_datetime=admit,
        discharge_datetime=admit + timedelta(days=5),
    )
    rec = CIFPatientRecord(
        patient=PatientProfile(patient_id=pid, sex="M", age=0),
        encounters=[enc],
        condition_event=ConditionEvent(
            condition_id="C1", condition_type="newborn_birth", ground_truth_diseases=["Z38.0"]
        ),
    )
    enrich_newborn(SimpleNamespace(records=[rec], config=SimpleNamespace(country=country)))
    return SimpleNamespace(record=rec, patient_id=pid, country=country.lower(), primary_enc_id=enc.encounter_id)


@pytest.mark.parametrize("country", ["US", "JP"])
def test_newborn_screen_report_and_result_name_a_resolvable_laboratory(country: str) -> None:
    ctx = _newborn(country)
    (org,) = _bb_newborn_screening_laboratory(ctx)
    (report,) = _bb_newborn_metabolic_screen_diagnostic_report(ctx)
    (obs,) = _bb_newborn_metabolic_screen_observation(ctx)
    ref = [{"reference": f"Organization/{org['id']}"}]
    assert report["performer"] == ref and obs["performer"] == ref
    assert org["resourceType"] == "Organization" and org["name"]


def test_laboratory_is_localized_per_country() -> None:
    us = _bb_newborn_screening_laboratory(_newborn("US"))[0]
    jp = _bb_newborn_screening_laboratory(_newborn("JP", 2))[0]
    assert us["name"].isascii() and "Public Health" in us["name"]
    assert not jp["name"].isascii()


def test_type_and_screen_report_names_the_hospital() -> None:
    order = {
        "order_id": "ORD-1",
        "encounter_id": "ENC-1",
        "display_name": "Type_and_screen",
        "ordered_datetime": "2025-03-01T10:00:00",
        "result": {"result_datetime": "2025-03-01T10:50:00", "value": "Negative"},
    }
    ctx = SimpleNamespace(
        record={"orders": [order], "encounters": [{"encounter_id": "ENC-1", "encounter_type": "inpatient"}]},
        patient_data={"blood_type": "A", "rh_factor": "+"},
        patient_id="P1",
        country="US",
        primary_enc_id="ENC-1",
    )
    report = next(r for r in _bb_blood_type(ctx) if r["resourceType"] == "DiagnosticReport")
    assert report["performer"] == [{"reference": "Organization/hospital-main"}]
