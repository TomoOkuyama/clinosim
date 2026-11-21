"""Issue #3463: the delivery discharge prescription carries on the mother's
maintenance home medications, so the discharge summary does not report them
stopped and the later postpartum visits (which list the same medications)
agree with it."""

from __future__ import annotations

from datetime import datetime

import numpy as np
import pytest

from clinosim.codes.drugs import drug_key
from clinosim.modules.staff.engine import StaffRoster
from clinosim.simulator.outpatient import OUTPATIENT_PRESCRIPTION_DURATION_DAYS
from clinosim.simulator.perinatal import simulate_delivery_encounter
from clinosim.types.allergy import Allergy
from clinosim.types.patient import HomeMedication, PatientProfile

pytestmark = pytest.mark.unit

_ADMIT = datetime(2025, 7, 15, 10, 0)
_HOME = [
    HomeMedication(drug_name="Folic acid", route="PO", dose="400mcg", frequency="daily"),
    HomeMedication(drug_name="Levothyroxine", route="PO", dose="50mcg", frequency="daily"),
]


def _rx_items(patient: PatientProfile) -> list[dict]:
    rec = simulate_delivery_encounter(
        patient=patient,
        visit_date=_ADMIT,
        roster=StaffRoster(),
        rng=np.random.default_rng(1),
        country="JP",
        hospital_ops={},
    )[0]
    return list(rec.discharge_prescription.items)


def _patient(**kw) -> PatientProfile:
    return PatientProfile(patient_id="POP-T3463", sex="F", age=30, current_medications=list(_HOME), **kw)


def test_home_medications_continue_after_delivery() -> None:
    items = _rx_items(_patient())
    by_name = {i["drug_name"]: i for i in items}
    for med in _HOME:
        item = by_name[med.drug_name]
        assert (item["dose"], item["route"], item["frequency"]) == (med.dose, med.route, med.frequency)
        assert item["duration_days"] == OUTPATIENT_PRESCRIPTION_DURATION_DAYS
    # the analgesics are still prescribed, once each
    assert {"Acetaminophen", "Ibuprofen"} <= set(by_name)
    assert len(items) == len({drug_key(i["drug_name"]) for i in items})


def test_no_home_drug_is_left_off_the_prescription() -> None:
    patient = _patient()
    keys = {drug_key(i["drug_name"]) for i in _rx_items(patient)}
    assert {drug_key(m.drug_name) for m in patient.current_medications} <= keys


def test_home_analgesic_is_not_prescribed_twice() -> None:
    patient = PatientProfile(
        patient_id="POP-T3463", sex="F", age=30, current_medications=[HomeMedication(drug_name="Ibuprofen", route="PO")]
    )
    names = [i["drug_name"] for i in _rx_items(patient)]
    assert names.count("Ibuprofen") == 1


def test_allergy_blocked_home_drug_is_not_continued() -> None:
    patient = PatientProfile(
        patient_id="POP-T3463",
        sex="F",
        age=30,
        current_medications=[HomeMedication(drug_name="Amoxicillin", route="PO", dose="250mg", frequency="tid")],
        allergies=[Allergy(allergen_code="764146007", category="medication")],  # penicillin
    )
    assert "Amoxicillin" not in [i["drug_name"] for i in _rx_items(patient)]


def test_no_home_medication_leaves_the_analgesic_bundle_unchanged() -> None:
    items = _rx_items(PatientProfile(patient_id="POP-T3463", sex="F", age=30))
    assert [i["drug_name"] for i in items] == ["Acetaminophen", "Ibuprofen"]
