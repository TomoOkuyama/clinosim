"""Health-checkup values read the medications in effect on the checkup date
(Issue #3199), not the medication list the simulation ends with."""

from __future__ import annotations

from datetime import datetime

import pytest

from clinosim.modules.patient.medication_timeline import medications_on, note_encounter_medications
from clinosim.types.encounter import Encounter, EncounterType
from clinosim.types.output import CIFPatientRecord
from clinosim.types.patient import HomeMedication, PatientProfile

pytestmark = pytest.mark.unit

_AMLODIPINE = HomeMedication(drug_name="Amlodipine", dose="5mg", frequency="daily")
_ATORVASTATIN = HomeMedication(drug_name="Atorvastatin", dose="10mg", frequency="daily")


def _visit(patient: PatientProfile, when: str, meds: list[HomeMedication]) -> None:
    """An encounter ending at ``when`` after which the patient takes ``meds``."""
    patient.current_medications = list(meds)
    end = datetime.fromisoformat(when)
    enc = Encounter(
        encounter_id=f"ENC-{when}",
        patient_id=patient.patient_id,
        encounter_type=EncounterType.OUTPATIENT,
        admission_datetime=end,
        discharge_datetime=end,
    )
    note_encounter_medications(CIFPatientRecord(patient=patient, encounters=[enc]))


def _names(meds: list[HomeMedication]) -> list[str]:
    return [m.drug_name for m in meds]


def test_a_drug_started_after_the_date_is_not_in_effect() -> None:
    patient = PatientProfile(patient_id="P1", age=55, sex="M")
    _visit(patient, "2026-03-01T10:00:00", [_AMLODIPINE])
    _visit(patient, "2026-09-01T10:00:00", [_AMLODIPINE, _ATORVASTATIN])
    assert _names(medications_on(patient, datetime(2026, 8, 3, 9))) == ["Amlodipine"]
    assert _names(medications_on(patient, datetime(2026, 9, 2, 9))) == ["Amlodipine", "Atorvastatin"]


def test_a_drug_stopped_after_the_date_is_still_in_effect() -> None:
    patient = PatientProfile(patient_id="P1", age=55, sex="M")
    _visit(patient, "2026-03-01T10:00:00", [_AMLODIPINE, _ATORVASTATIN])
    _visit(patient, "2026-09-01T10:00:00", [_AMLODIPINE])
    assert _names(medications_on(patient, datetime(2026, 8, 3, 9))) == ["Amlodipine", "Atorvastatin"]


def test_before_the_first_encounter_the_medications_it_started_with_apply() -> None:
    patient = PatientProfile(patient_id="P1", age=55, sex="M", current_medications=[_AMLODIPINE])
    patient.visit_ledger.medications_at_activation = (_AMLODIPINE,)
    _visit(patient, "2026-09-01T10:00:00", [_AMLODIPINE, _ATORVASTATIN])
    assert _names(medications_on(patient, datetime(2026, 8, 3, 9))) == ["Amlodipine"]


def test_without_a_timeline_the_current_medications_apply() -> None:
    patient = PatientProfile(patient_id="P1", age=55, sex="M", current_medications=[_ATORVASTATIN])
    assert _names(medications_on(patient, datetime(2026, 8, 3, 9))) == ["Atorvastatin"]


def test_the_checkup_record_carries_the_medications_of_the_checkup_date() -> None:
    from clinosim.modules.health_checkup.engine import _patient_selected, enrich_health_checkup
    from clinosim.simulator.enrichers import EnricherContext
    from clinosim.types.config import SimulatorConfig

    pid = next(f"POP-{i:06d}" for i in range(1000) if _patient_selected(f"POP-{i:06d}"))
    patient = PatientProfile(patient_id=pid, age=55, sex="M")
    # Checkup dates fall inside the year before the snapshot; a statin
    # started after the snapshot is after any checkup date.
    _visit(patient, "2025-10-01T10:00:00", [_AMLODIPINE])
    _visit(patient, "2026-11-02T10:00:00", [_AMLODIPINE, _ATORVASTATIN])
    record = CIFPatientRecord(patient=patient)
    cfg = SimulatorConfig(country="JP", modules={"health_checkup": True}, snapshot_date="2026-11-01")
    ctx = EnricherContext(config=cfg, master_seed=42, records=[record])
    enrich_health_checkup(ctx)
    [checkup] = ctx.records[1:]
    assert _names(checkup.patient.current_medications) == ["Amlodipine"]
    # The patient's own (end-of-simulation) list is unchanged.
    assert _names(patient.current_medications) == ["Amlodipine", "Atorvastatin"]
