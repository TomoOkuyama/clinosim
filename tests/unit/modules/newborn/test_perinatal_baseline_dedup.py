"""Issue #1736: once-per-newborn hearing + metabolic screens must not
re-emit when the same ``-BABY`` ``patient_id`` reappears in a second
``newborn_birth`` CIF record.

Mechanism in production (as surfaced by the p=2000 US seed=42 5y audit):
a mother with ≥ 2 deliveries lands two newborn-side CIF records that
both carry ``patient_id = f"{mother_id}-BABY"`` with
``condition_event.condition_type = "newborn_birth"``. Pre-fix, the
newborn enricher fires the AABR hearing screen (SNOMED 232717001) and
the tandem-MS metabolic screen (SNOMED 405058008) on EACH record,
producing a duplicate once-per-newborn Procedure under the shared
``-BABY`` subject reference — 14 % of babies at p=2000 US 5y.

This test exercises that path directly: run ``enrich_newborn`` on two
back-to-back birth records sharing the ``-BABY`` id and assert the
hearing + metabolic Procedures fire on the first only. Mirrors the
Phase 4d ``baseline_only`` dedup pattern already in
``simulator/outpatient.py`` for CPAP / polysomnography.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from clinosim.modules.newborn import enrich_newborn
from clinosim.types.clinical import ConditionEvent
from clinosim.types.encounter import Encounter, EncounterType
from clinosim.types.output import CIFPatientRecord
from clinosim.types.patient import PatientProfile

pytestmark = pytest.mark.unit


def _birth_record(patient_id: str, admit: datetime, los_days: int = 2) -> CIFPatientRecord:
    enc = Encounter(
        encounter_id=f"ENC-{patient_id}-{admit:%Y%m%d}",
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


class _Cfg:
    def __init__(self, country: str) -> None:
        self.country = country


class _Ctx:
    def __init__(self, records: list, country: str = "US") -> None:
        self.records = records
        self.config = _Cfg(country)


def _codes(record: CIFPatientRecord) -> set[str]:
    return {p.procedure_code for p in (record.procedures or [])}


def test_hearing_screen_dedup_across_sibling_birth_records_us() -> None:
    """US baby: first delivery emits SNOMED 232717001; a second delivery
    under the same ``POP-xxx-BABY`` id does NOT re-emit."""
    pid = "POP-010000-BABY"
    first = _birth_record(pid, datetime(2026, 6, 1, 10, 0), los_days=2)
    second = _birth_record(pid, datetime(2029, 11, 1, 10, 0), los_days=2)

    enrich_newborn(_Ctx(records=[first], country="US"))
    enrich_newborn(_Ctx(records=[second], country="US"))

    assert "232717001" in _codes(first)
    assert "232717001" not in _codes(second), (
        f"hearing screen 232717001 re-emitted on 2nd birth record for {pid}: codes={_codes(second)}"
    )


def test_metabolic_screen_dedup_across_sibling_birth_records_us() -> None:
    """US baby: first delivery emits SNOMED 405058008; a second delivery
    under the same ``POP-xxx-BABY`` id does NOT re-emit."""
    pid = "POP-010001-BABY"
    first = _birth_record(pid, datetime(2026, 6, 1, 10, 0), los_days=2)
    second = _birth_record(pid, datetime(2029, 11, 1, 10, 0), los_days=2)

    enrich_newborn(_Ctx(records=[first], country="US"))
    enrich_newborn(_Ctx(records=[second], country="US"))

    assert "405058008" in _codes(first)
    assert "405058008" not in _codes(second), (
        f"metabolic screen 405058008 re-emitted on 2nd birth record for {pid}: codes={_codes(second)}"
    )


def test_metabolic_screen_workflow_also_dedupped_us() -> None:
    """Suppressing the metabolic Procedure must also suppress the
    sibling ServiceRequest / Specimen / DiagnosticReport workflow stash
    under ``extensions.newborn.metabolic_screen`` — the two emit paths
    must stay in lock-step so the FHIR bundle never ships SR / Specimen /
    DR without a corresponding Procedure.
    """
    pid = "POP-010002-BABY"
    first = _birth_record(pid, datetime(2026, 6, 1, 10, 0), los_days=5)
    second = _birth_record(pid, datetime(2029, 11, 1, 10, 0), los_days=5)

    enrich_newborn(_Ctx(records=[first], country="JP"))
    enrich_newborn(_Ctx(records=[second], country="JP"))

    first_nb = (first.extensions or {}).get("newborn", {})
    second_nb = (second.extensions or {}).get("newborn", {})
    assert "metabolic_screen" in first_nb
    assert "metabolic_screen" not in second_nb, (
        f"metabolic_screen workflow stash leaked onto 2nd birth record for {pid}"
    )


def test_dedup_does_not_affect_distinct_baby_patient_ids() -> None:
    """Sanity: dedup is scoped per-patient_id — a different ``-BABY``
    patient still gets its own one-shot screens."""
    sib_a = _birth_record("POP-010003-BABY", datetime(2026, 6, 1, 10, 0), los_days=2)
    sib_b = _birth_record("POP-010004-BABY", datetime(2026, 7, 1, 10, 0), los_days=2)

    enrich_newborn(_Ctx(records=[sib_a], country="US"))
    enrich_newborn(_Ctx(records=[sib_b], country="US"))

    assert "232717001" in _codes(sib_a)
    assert "405058008" in _codes(sib_a)
    assert "232717001" in _codes(sib_b)
    assert "405058008" in _codes(sib_b)
