"""Unit tests for newborn birth-admission shift-cadence vital signs
(#1252 N3).
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from clinosim.modules.newborn import (
    build_newborn_shift_vitals,
    enrich_newborn,
)
from clinosim.types.clinical import ConditionEvent
from clinosim.types.encounter import Encounter, EncounterType
from clinosim.types.output import CIFPatientRecord
from clinosim.types.patient import BaselineVitals, PatientProfile

pytestmark = pytest.mark.unit


def _newborn_record(los_days: int = 5) -> CIFPatientRecord:
    admit = datetime(2026, 6, 1, 10, 0)
    enc = Encounter(
        encounter_id="ENC-BABY-1",
        patient_id="POP-000001-BABY",
        encounter_type=EncounterType.INPATIENT,
        admission_datetime=admit,
        discharge_datetime=admit + timedelta(days=los_days),
    )
    return CIFPatientRecord(
        patient=PatientProfile(
            patient_id="POP-000001-BABY",
            sex="M",
            age=0,
            # Neonatal baseline_vitals (seeded by perinatal.py::_build_newborn_patient
            # for real cohorts; hardcoded here to keep the test self-contained).
            baseline_vitals=BaselineVitals(
                temperature=36.7,
                heart_rate=130,
                systolic_bp=68,
                diastolic_bp=40,
                respiratory_rate=40,
                spo2=97,
            ),
        ),
        encounters=[enc],
        condition_event=ConditionEvent(
            condition_id="COND-POP-000001-BABY-BIRTH",
            condition_type="newborn_birth",
            ground_truth_diseases=["Z38.0"],
        ),
    )


def _adult_record() -> CIFPatientRecord:
    admit = datetime(2026, 6, 1, 10, 0)
    enc = Encounter(
        encounter_id="ENC-A-1",
        patient_id="POP-A",
        encounter_type=EncounterType.INPATIENT,
        admission_datetime=admit,
        discharge_datetime=admit + timedelta(days=3),
    )
    return CIFPatientRecord(
        patient=PatientProfile(patient_id="POP-A", sex="F", age=45),
        encounters=[enc],
        condition_event=ConditionEvent(condition_type="pneumonia_acute"),
    )


class _Cfg:
    def __init__(self, country: str) -> None:
        self.country = country


class _Ctx:
    def __init__(self, records: list, country: str = "JP") -> None:
        self.records = records
        self.config = _Cfg(country)


def test_newborn_shift_vitals_span_the_birth_admission_los() -> None:
    """5-day JP birth admission (admit 06/01 10:00 → discharge 06/06 10:00)
    covers ≥ 14 vital sets: 1 at admission + 5 days × 3 shifts = 16 max,
    minus any that fall past discharge (day 5 evening 16:00 falls past
    the 10:00 discharge → skipped). Every emitted VitalSignRecord
    carries the neonatal baseline verbatim.
    """
    rec = _newborn_record(los_days=5)
    vitals = build_newborn_shift_vitals(rec)
    admit = rec.encounters[0].admission_datetime
    dischg = rec.encounters[0].discharge_datetime
    assert vitals, "expected shift-cadence vital sets for a 5-day newborn admission"
    # Every timestamp lies inside [admit, discharge].
    for v in vitals:
        assert admit <= v.timestamp <= dischg
    # First entry lands exactly at admission (arrival vital set).
    assert vitals[0].timestamp == admit
    # Neonatal values carried through.
    assert all(v.heart_rate == 130 for v in vitals)
    assert all(v.systolic_bp == 68 for v in vitals)
    assert all(v.respiratory_rate == 40 for v in vitals)
    assert all(v.temperature_celsius == pytest.approx(36.7) for v in vitals)


def test_newborn_shift_vitals_deterministic_across_reruns() -> None:
    a = build_newborn_shift_vitals(_newborn_record(los_days=5))
    b = build_newborn_shift_vitals(_newborn_record(los_days=5))
    assert [v.timestamp for v in a] == [v.timestamp for v in b]
    assert all(av.heart_rate == bv.heart_rate for av, bv in zip(a, b))


def test_newborn_shift_vitals_noop_on_adult_record() -> None:
    assert build_newborn_shift_vitals(_adult_record()) == []


def test_enricher_appends_vitals_to_newborn_only() -> None:
    """The POST_ENCOUNTER enricher appends both Vitamin K MAR entries
    AND shift-cadence vital signs to the newborn record; the adult
    record's `vital_signs` list stays untouched.
    """
    baby = _newborn_record(los_days=5)
    adult = _adult_record()
    ctx = _Ctx(records=[baby, adult], country="JP")
    enrich_newborn(ctx)
    assert len(baby.vital_signs) >= 14, "expected shift-cadence vital sets across a 5-day LOS"
    assert adult.vital_signs == []
