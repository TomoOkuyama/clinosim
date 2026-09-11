"""Unit tests for newborn AABR hearing screen `ProcedureRecord`
emission (#1252 N5).
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from clinosim.modules.newborn import (
    build_hearing_screen_procedure,
    enrich_newborn,
)
from clinosim.types.clinical import ConditionEvent
from clinosim.types.encounter import Encounter, EncounterType
from clinosim.types.output import CIFPatientRecord
from clinosim.types.patient import PatientProfile

pytestmark = pytest.mark.unit


def _newborn_record(patient_id: str = "POP-000001-BABY", los_days: int = 5) -> CIFPatientRecord:
    admit = datetime(2026, 6, 1, 10, 0)
    enc = Encounter(
        encounter_id=f"ENC-{patient_id}-01",
        patient_id=patient_id,
        encounter_type=EncounterType.INPATIENT,
        admission_datetime=admit,
        discharge_datetime=admit + timedelta(days=los_days),
    )
    return CIFPatientRecord(
        patient=PatientProfile(patient_id=patient_id, sex="M", age=0),
        encounters=[enc],
        condition_event=ConditionEvent(
            condition_id=f"COND-{patient_id}-BIRTH",
            condition_type="newborn_birth",
            ground_truth_diseases=["Z38.0"],
        ),
    )


def _adult_record() -> CIFPatientRecord:
    return CIFPatientRecord(
        patient=PatientProfile(patient_id="POP-A", sex="F", age=45),
        encounters=[
            Encounter(
                admission_datetime=datetime(2026, 6, 1, 10, 0),
                discharge_datetime=datetime(2026, 6, 3, 10, 0),
            )
        ],
        condition_event=ConditionEvent(condition_type="pneumonia_acute"),
    )


class _Cfg:
    def __init__(self, country: str) -> None:
        self.country = country


class _Ctx:
    def __init__(self, records: list, country: str = "JP") -> None:
        self.records = records
        self.config = _Cfg(country)


def test_hearing_screen_emitted_for_newborn() -> None:
    proc = build_hearing_screen_procedure(_newborn_record())
    assert proc is not None
    assert proc.procedure_type == "hearing_screen_aabr"
    assert proc.procedure_code == "232717001"  # SNOMED AABR screening
    assert proc.category_code == "103693007"  # diagnostic procedure
    # outcome_code is one of the two configured SNOMED codes.
    assert proc.outcome_code in ("385669000", "385671000")
    # Scheduled within the birth admission.
    admit = _newborn_record().encounters[0].admission_datetime
    assert proc.start_datetime > admit
    assert proc.duration_minutes == 15


def test_hearing_screen_deterministic() -> None:
    a = build_hearing_screen_procedure(_newborn_record("POP-000042-BABY"))
    b = build_hearing_screen_procedure(_newborn_record("POP-000042-BABY"))
    assert a is not None and b is not None
    assert a.outcome_code == b.outcome_code
    assert a.start_datetime == b.start_datetime


def test_hearing_screen_pass_rate_across_cohort() -> None:
    """~97 % of babies pass on first AABR (per newborn_screening.yaml
    result_weights). Loose 90 % floor to allow small-cohort variance.
    """
    n = 100
    passes = 0
    for i in range(n):
        proc = build_hearing_screen_procedure(_newborn_record(f"POP-{i:05d}-BABY"))
        if proc is not None and proc.outcome_code == "385669000":
            passes += 1
    assert passes >= n * 0.90, f"only {passes}/{n} passed; expected ≥ 90"


def test_hearing_screen_no_op_on_adult() -> None:
    assert build_hearing_screen_procedure(_adult_record()) is None


def test_hearing_screen_skipped_when_past_discharge() -> None:
    """A 6-hour LOS is too short for the 24 h-after-admission screen."""
    admit = datetime(2026, 6, 1, 10, 0)
    rec = CIFPatientRecord(
        patient=PatientProfile(patient_id="POP-Q-BABY", sex="M", age=0),
        encounters=[
            Encounter(
                encounter_id="ENC-Q-01",
                patient_id="POP-Q-BABY",
                admission_datetime=admit,
                discharge_datetime=admit + timedelta(hours=6),
            )
        ],
        condition_event=ConditionEvent(condition_type="newborn_birth"),
    )
    assert build_hearing_screen_procedure(rec) is None


def test_enricher_appends_hearing_procedure_to_newborn_only() -> None:
    baby = _newborn_record()
    adult = _adult_record()
    ctx = _Ctx(records=[baby, adult], country="JP")
    enrich_newborn(ctx)
    hearing = [p for p in baby.procedures if p.procedure_type == "hearing_screen_aabr"]
    assert len(hearing) == 1
    assert adult.procedures == []
