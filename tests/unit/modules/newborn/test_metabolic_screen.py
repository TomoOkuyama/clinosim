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


def test_metabolic_screen_emitted_for_jp_newborn_day_4() -> None:
    proc = build_metabolic_screen_procedure(_newborn_record(), country="JP")
    assert proc is not None
    assert proc.procedure_type == "metabolic_screen_tandem_ms"
    assert proc.procedure_code == "405058008"  # SNOMED Neonatal screening
    assert proc.category_code == "103693007"  # diagnostic
    assert proc.outcome_code in ("385669000", "385671000")
    admit = _newborn_record().encounters[0].admission_datetime
    # JP: heel-stick day 4 before 5-day discharge.
    assert proc.start_datetime.date() == (admit + timedelta(days=4)).date()


def test_metabolic_screen_emitted_for_us_newborn_day_1() -> None:
    """US: heel-stick day 1 (24h) before typical 2-day discharge — US
    EHDI Act universal-screening cohort. Prior to #1263 the shared
    day-4 slot silently skipped every well-newborn US baby.
    """
    rec = _newborn_record(los_days=2)  # US LOS default
    proc = build_metabolic_screen_procedure(rec, country="US")
    assert proc is not None
    admit = rec.encounters[0].admission_datetime
    assert proc.start_datetime.date() == (admit + timedelta(days=1)).date()
    # SNOMED procedure/category codes are locale-invariant.
    assert proc.procedure_code == "405058008"
    assert proc.category_code == "103693007"


def test_metabolic_screen_deterministic() -> None:
    a = build_metabolic_screen_procedure(_newborn_record("POP-000042-BABY"), country="JP")
    b = build_metabolic_screen_procedure(_newborn_record("POP-000042-BABY"), country="JP")
    assert a is not None and b is not None
    assert a.outcome_code == b.outcome_code
    assert a.start_datetime == b.start_datetime


def test_metabolic_screen_high_pass_rate_across_cohort() -> None:
    """~99.7% pass in real cohorts. Loose 95% floor to allow variance."""
    n = 100
    passes = 0
    for i in range(n):
        proc = build_metabolic_screen_procedure(_newborn_record(f"POP-{i:05d}-BABY"), country="JP")
        if proc is not None and proc.outcome_code == "385669000":
            passes += 1
    assert passes >= n * 0.95, f"only {passes}/{n} passed; expected ≥ 95"


def test_metabolic_screen_no_op_on_adult() -> None:
    assert build_metabolic_screen_procedure(_adult_record(), country="JP") is None
    assert build_metabolic_screen_procedure(_adult_record(), country="US") is None


def test_metabolic_screen_skipped_when_los_shorter_than_schedule_jp() -> None:
    """Defensive gate: LOS 3-day JP is shorter than the day-4 slot."""
    rec = _newborn_record(los_days=3)
    assert build_metabolic_screen_procedure(rec, country="JP") is None


def test_metabolic_screen_us_los_2_not_skipped() -> None:
    """Regression guard for #1263: a US 2-day LOS newborn must NOT be
    silently dropped — that was the bug.
    """
    rec = _newborn_record(los_days=2)
    proc = build_metabolic_screen_procedure(rec, country="US")
    assert proc is not None


def test_enricher_appends_both_screens_to_jp_newborn() -> None:
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


def test_enricher_appends_both_screens_to_us_newborn() -> None:
    """Same coverage guarantee for the US locale (#1263)."""
    baby = _newborn_record(los_days=2)  # US LOS default
    ctx = _Ctx(records=[baby], country="US")
    enrich_newborn(ctx)
    proc_types = {p.procedure_type for p in baby.procedures}
    assert "hearing_screen_aabr" in proc_types
    assert "metabolic_screen_tandem_ms" in proc_types
