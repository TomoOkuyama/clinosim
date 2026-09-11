"""Unit tests for the newborn-birth-admission Vitamin K prophylaxis
event emission (#1252 N2 slice).
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from clinosim.modules.newborn import (
    build_vitamin_k_administrations,
    enrich_newborn,
    is_newborn_birth_record,
)
from clinosim.types.clinical import ConditionEvent
from clinosim.types.encounter import Encounter, EncounterType
from clinosim.types.output import CIFPatientRecord
from clinosim.types.patient import PatientProfile

pytestmark = pytest.mark.unit


def _newborn_record(los_days: int = 5, encounter_id: str = "ENC-BABY-1") -> CIFPatientRecord:
    admit = datetime(2026, 6, 1, 10, 0)
    enc = Encounter(
        encounter_id=encounter_id,
        patient_id="POP-000001-BABY",
        encounter_type=EncounterType.INPATIENT,
        admission_datetime=admit,
        discharge_datetime=admit + timedelta(days=los_days),
    )
    return CIFPatientRecord(
        patient=PatientProfile(patient_id="POP-000001-BABY", sex="M", age=0),
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
        patient_id="POP-000001",
        encounter_type=EncounterType.INPATIENT,
        admission_datetime=admit,
        discharge_datetime=admit + timedelta(days=3),
    )
    return CIFPatientRecord(
        patient=PatientProfile(patient_id="POP-000001", sex="F", age=45),
        encounters=[enc],
        condition_event=ConditionEvent(condition_type="pneumonia_acute", ground_truth_diseases=["J18.9"]),
    )


class _Cfg:
    def __init__(self, country: str) -> None:
        self.country = country


class _Ctx:
    def __init__(self, records: list, country: str = "JP") -> None:
        self.records = records
        self.config = _Cfg(country)


def test_newborn_birth_gate_positive() -> None:
    assert is_newborn_birth_record(_newborn_record()) is True


def test_newborn_birth_gate_negative_for_adult() -> None:
    assert is_newborn_birth_record(_adult_record()) is False


def test_jp_vitamin_k_emits_two_doses_over_a_7day_los() -> None:
    """JP schedule = days 0 + 7. A 7-day LOS captures both doses; the
    engine emits them as MAR entries within the birth-encounter window.
    """
    rec = _newborn_record(los_days=7)
    mars = build_vitamin_k_administrations(rec, country="JP")
    assert len(mars) == 2, "JP schedule should emit 2 doses for a 7-day LOS"
    admit = rec.encounters[0].admission_datetime
    dose_1_delta_hours = (mars[0].scheduled_datetime - admit).total_seconds() / 3600
    assert 0 < dose_1_delta_hours <= 24, "dose 1 must land within 24 h of birth"
    assert mars[0].route == "PO"
    assert "経口" in mars[0].drug_name or "フィトナジオン" in mars[0].drug_name
    assert mars[0].status == "given"
    # Dose 2 sits ~ day 7.
    dose_2_delta_days = (mars[1].scheduled_datetime - admit).days
    assert 6 <= dose_2_delta_days <= 7


def test_jp_vitamin_k_omits_dose_past_discharge() -> None:
    """A 3-day JP LOS drops the day-7 dose — it falls past discharge."""
    rec = _newborn_record(los_days=3)
    mars = build_vitamin_k_administrations(rec, country="JP")
    assert len(mars) == 1, "3-day LOS should keep only the day-0 dose"


def test_us_vitamin_k_emits_single_im_dose() -> None:
    rec = _newborn_record(los_days=2)
    mars = build_vitamin_k_administrations(rec, country="US")
    assert len(mars) == 1
    assert mars[0].route == "IM"
    assert "Vitamin K" in mars[0].drug_name or "phytonadione" in mars[0].drug_name.lower()
    admit = rec.encounters[0].admission_datetime
    hours = (mars[0].scheduled_datetime - admit).total_seconds() / 3600
    assert 0 < hours <= 6, "US dose 1 must land within 6 h of birth"


def test_engine_noop_for_non_newborn_record() -> None:
    assert build_vitamin_k_administrations(_adult_record(), country="JP") == []


def test_enricher_appends_mars_only_to_newborn_records() -> None:
    """The POST_ENCOUNTER enricher must append MAR entries only to the
    newborn record; the adult record's medication_administrations list
    stays untouched.
    """
    newborn = _newborn_record(los_days=5)
    adult = _adult_record()
    ctx = _Ctx(records=[newborn, adult], country="JP")
    enrich_newborn(ctx)
    assert len(newborn.medication_administrations) >= 1
    assert all("フィトナジオン" in m.drug_name or "経口" in m.drug_name for m in newborn.medication_administrations)
    assert adult.medication_administrations == []
