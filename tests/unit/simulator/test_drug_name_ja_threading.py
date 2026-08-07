"""Threading of drug_name_ja through discharge_prescription.items[] (Issue #440 short-term (a)).

Verifies that `_deactivate_to_layer1` re-inflates HomeMedication with `drug_name_ja`
preserved after round-trip through the dict-based `discharge_prescription.items`.
Prior to the fix, `drug_name_ja` was silently dropped because the intermediate
dict did not carry the field (Cross-ref from #442 PR 1).
"""

from __future__ import annotations

from datetime import date, datetime

from clinosim.simulator.helpers import _deactivate_to_layer1
from clinosim.types.encounter import Encounter, PrescriptionRecord
from clinosim.types.output import CIFPatientRecord
from clinosim.types.patient import HomeMedication, PatientProfile
from clinosim.types.population import PersonRecord


def _make_person(person_id: str = "POP-TEST") -> PersonRecord:
    return PersonRecord(
        person_id=person_id,
        household_id="HH-TEST",
        age=65,
        sex="F",
        date_of_birth=date(1960, 1, 1),
    )


def _make_profile(person_id: str = "POP-TEST") -> PatientProfile:
    return PatientProfile(
        patient_id=person_id,
        household_id="HH-TEST",
        age=65,
        sex="F",
        date_of_birth=date(1960, 1, 1),
    )


def _make_record_with_rx(person_id: str, items: list[dict]) -> CIFPatientRecord:
    rx = PrescriptionRecord(
        prescription_id=f"RX-{person_id}",
        patient_id=person_id,
        prescriber_id="STAFF-1",
        issue_date=datetime(2025, 6, 1),
        items=items,
    )
    return CIFPatientRecord(
        patient=_make_profile(person_id),
        encounters=[
            Encounter(
                encounter_id=f"ENC-{person_id}",
                patient_id=person_id,
                admission_datetime=datetime(2025, 5, 28),
                discharge_datetime=datetime(2025, 6, 1),
            )
        ],
        discharge_prescription=rx,
    )


def test_deactivate_preserves_drug_name_ja_when_present():
    """discharge_prescription.items[] carrying drug_name_ja round-trips into current_medications."""
    person = _make_person()
    profile = _make_profile()
    patient_cache = {person.person_id: profile}
    record = _make_record_with_rx(
        person.person_id,
        items=[
            {
                "drug_name": "Amlodipine",
                "drug_name_ja": "アムロジピン",
                "dose": "5mg",
                "route": "PO",
                "frequency": "daily",
            }
        ],
    )
    _deactivate_to_layer1(person, record, "hypertension", patient_cache=patient_cache)
    assert len(person.current_medications) == 1
    med = person.current_medications[0]
    assert isinstance(med, HomeMedication)
    assert med.drug_name == "Amlodipine"
    assert med.drug_name_ja == "アムロジピン"
    # Cache profile also synced
    assert patient_cache[person.person_id].current_medications[0].drug_name_ja == "アムロジピン"


def test_deactivate_absent_drug_name_ja_stays_empty():
    """Backcompat: item without drug_name_ja key results in empty string (no crash)."""
    person = _make_person()
    profile = _make_profile()
    patient_cache = {person.person_id: profile}
    record = _make_record_with_rx(
        person.person_id,
        items=[
            {
                "drug_name": "Aspirin",
                "dose": "100mg",
                "route": "PO",
                "frequency": "daily",
            }
        ],
    )
    _deactivate_to_layer1(person, record, "acute_mi", patient_cache=patient_cache)
    assert person.current_medications[0].drug_name_ja == ""
