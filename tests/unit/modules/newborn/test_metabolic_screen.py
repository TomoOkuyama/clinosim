"""Unit tests for the newborn tandem-MS metabolic screening
`ProcedureRecord` emission (#1252 N6, minimum-viable slice).
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from clinosim.modules.newborn import (
    build_metabolic_screen_procedure,
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


def test_metabolic_screen_emitted_for_newborn() -> None:
    proc = build_metabolic_screen_procedure(_newborn_record())
    assert proc is not None
    assert proc.procedure_type == "metabolic_screen_tandem_ms"
    assert proc.procedure_code == "405058008"  # SNOMED Neonatal screening
    assert proc.category_code == "103693007"  # diagnostic
    assert proc.outcome_code in ("385669000", "385671000")
    admit = _newborn_record().encounters[0].admission_datetime
    # Collection lands day 4 (per yaml).
    assert proc.start_datetime.date() == (admit + timedelta(days=4)).date()


def test_metabolic_screen_deterministic() -> None:
    a = build_metabolic_screen_procedure(_newborn_record("POP-000042-BABY"))
    b = build_metabolic_screen_procedure(_newborn_record("POP-000042-BABY"))
    assert a is not None and b is not None
    assert a.outcome_code == b.outcome_code
    assert a.start_datetime == b.start_datetime


def test_metabolic_screen_high_pass_rate_across_cohort() -> None:
    """~99.7% pass in real cohorts. Loose 95% floor to allow variance."""
    n = 100
    passes = 0
    for i in range(n):
        proc = build_metabolic_screen_procedure(_newborn_record(f"POP-{i:05d}-BABY"))
        if proc is not None and proc.outcome_code == "385669000":
            passes += 1
    assert passes >= n * 0.95, f"only {passes}/{n} passed; expected ≥ 95"


def test_metabolic_screen_no_op_on_adult() -> None:
    assert build_metabolic_screen_procedure(_adult_record()) is None


def test_metabolic_screen_skipped_when_los_shorter_than_schedule() -> None:
    """A 2-day US LOS is shorter than the day-4 metabolic-screen slot."""
    rec = _newborn_record(los_days=2)
    assert build_metabolic_screen_procedure(rec) is None


def test_enricher_appends_both_screens_to_newborn() -> None:
    """After the enricher runs, a JP baby's `procedures` list carries
    BOTH the hearing screen (N5) AND the metabolic screen (N6).
    """
    baby = _newborn_record()
    adult = _adult_record()
    ctx = _Ctx(records=[baby, adult], country="JP")
    enrich_newborn(ctx)
    proc_types = {p.procedure_type for p in baby.procedures}
    assert "hearing_screen_aabr" in proc_types
    assert "metabolic_screen_tandem_ms" in proc_types
    assert adult.procedures == []
