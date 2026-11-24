"""The ED triage note is authored by the triage nurse (Issue #3703)."""

from __future__ import annotations

import logging
from datetime import datetime
from types import SimpleNamespace

import pytest

from clinosim import determinism
from clinosim.locale.loader import load_demographics
from clinosim.modules.document.engine import _pick_document_author
from clinosim.modules.document.narrative.registry import load_document_type_specs
from clinosim.modules.encounter.protocol import load_encounter_condition
from clinosim.modules.patient.activator import activate_patient
from clinosim.modules.population.engine import PersonRecord
from clinosim.modules.staff.engine import generate_roster
from clinosim.simulator.emergency import _simulate_ed_visit
from clinosim.types.document import DocumentType

pytestmark = pytest.mark.unit

_HOSPITAL = {
    "available_departments": ["emergency_medicine", "internal_medicine"],
    "wards": {"emergency_medicine": ["ER"], "internal_medicine": ["3N"]},
    "resource_capacity": {"inpatient_beds": 120, "operating_rooms": 3},
}
_TRIAGE = "54094-8"
_ED_NOTE = "34878-9"


def _spec(loinc: str) -> SimpleNamespace:
    specs = [s for s in load_document_type_specs().values() if s.loinc_code == loinc]
    assert specs, loinc
    return specs[0]


def test_triage_note_spec_declares_the_triage_nurse_author() -> None:
    assert load_document_type_specs()[DocumentType("ed_triage_note")].author_role == "triage_nurse"


def test_triage_note_is_authored_by_the_triage_nurse() -> None:
    enc = SimpleNamespace(attending_physician_id="DR-EM-003", triage_nurse_id="NS-EM-001", primary_nurse_id="")
    assert _pick_document_author(_spec(_TRIAGE), enc) == "NS-EM-001"


def test_ed_physician_note_keeps_the_physician() -> None:
    enc = SimpleNamespace(attending_physician_id="DR-EM-003", triage_nurse_id="NS-EM-001", primary_nurse_id="")
    assert _pick_document_author(_spec(_ED_NOTE), enc) == "DR-EM-003"


def test_no_triage_nurse_falls_back_to_the_attending(caplog: pytest.LogCaptureFixture) -> None:
    enc = SimpleNamespace(attending_physician_id="DR-EM-003", triage_nurse_id="")
    with caplog.at_level(logging.WARNING):
        assert _pick_document_author(_spec(_TRIAGE), enc) == "DR-EM-003"
    assert any("triage_nurse_id" in r.message for r in caplog.records)


@pytest.mark.parametrize("country", ["US", "JP"])
def test_ed_visit_records_the_nurse_who_charted_the_triage_vitals(country: str) -> None:
    rng = determinism.default_rng(3)
    roster = generate_roster("medium", country, rng, hospital_config=_HOSPITAL)
    person = PersonRecord(
        person_id="T-1", household_id="H-1", age=40, sex="M", date_of_birth=datetime(1984, 1, 1).date()
    )
    patient = activate_patient(person, rng, load_demographics(country))
    record = _simulate_ed_visit(
        patient, load_encounter_condition("animal_bite"), datetime(2024, 6, 1, 14, 0), roster, rng, country=country
    )
    [enc] = record.encounters
    assert enc.triage_nurse_id.startswith("NS-EM-")
    assert record.vital_signs[0].measured_by == enc.triage_nurse_id


def test_via_ed_admission_records_the_triage_nurse() -> None:
    """A stay admitted through the ED: the nurse who charts the arrival vitals
    is the author of the ED-phase triage note."""
    from clinosim.modules.triage.engine import _record_ed_arrival_vitals
    from clinosim.types.clinical import PhysiologicalState

    rng = determinism.default_rng(3)
    roster = generate_roster("medium", "US", rng, hospital_config=_HOSPITAL)
    person = PersonRecord(
        person_id="T-2", household_id="H-2", age=60, sex="F", date_of_birth=datetime(1964, 1, 1).date()
    )
    patient = activate_patient(person, rng, load_demographics("US"))
    enc = SimpleNamespace(encounter_id="ENC-T-2-1", severity="moderate", triage_nurse_id="")
    record = SimpleNamespace(
        physiological_states=[PhysiologicalState()],
        patient=patient,
        condition_event=None,
        vital_signs=[],
    )
    _record_ed_arrival_vitals(SimpleNamespace(roster=roster), record, enc, datetime(2024, 6, 1, 14, 0), rng)
    assert enc.triage_nurse_id.startswith("NS-EM-")
    assert record.vital_signs[0].measured_by == enc.triage_nurse_id
