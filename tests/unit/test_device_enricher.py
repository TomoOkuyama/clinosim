"""Unit tests for clinosim.modules.device.enricher (PR-A)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import pytest

from clinosim.modules.device.enricher import enrich_device
from clinosim.simulator.seeding import ENRICHER_SEED_OFFSETS
from clinosim.types.encounter import Encounter, EncounterType
from clinosim.types.output import CIFPatientRecord

pytestmark = pytest.mark.unit


@dataclass
class _Ctx:
    """Minimal EnricherContext stand-in for unit tests."""
    config: Any = None
    master_seed: int = 42
    population: Any = None
    records: list = field(default_factory=list)


def test_device_offset_registered():
    assert ENRICHER_SEED_OFFSETS["device"] == 0x4445


def test_enrich_device_empty_records_noop():
    ctx = _Ctx(records=[])
    enrich_device(ctx)
    assert ctx.records == []


def test_enrich_device_non_icu_patient_no_extensions_key():
    rec = CIFPatientRecord()
    rec.icu_transferred = False
    rec.encounters = [
        Encounter(
            encounter_id="enc1",
            encounter_type=EncounterType.INPATIENT,
            admission_datetime=datetime(2026, 1, 1),
            discharge_datetime=datetime(2026, 1, 5),
        )
    ]
    ctx = _Ctx(records=[rec])
    enrich_device(ctx)
    assert "device" not in rec.extensions


def test_enrich_device_icu_inpatient_writes_extensions():
    rec = CIFPatientRecord()
    rec.icu_transferred = True
    rec.encounters = [
        Encounter(
            encounter_id="enc1",
            encounter_type=EncounterType.INPATIENT,
            admission_datetime=datetime(2026, 1, 1),
            discharge_datetime=datetime(2026, 1, 5),
        )
    ]
    rec.patient.patient_id = "pid_test"
    ctx = _Ctx(records=[rec])
    enrich_device(ctx)
    assert "device" in rec.extensions
    devices = rec.extensions["device"]
    assert len(devices) >= 2  # at least CVC + indwelling_catheter from ICU
    types = {d.device_type for d in devices}
    assert "cvc" in types
    assert "indwelling_catheter" in types


def test_enrich_device_sub_seed_independent_of_master_seed():
    """Different master_seeds produce same device IDs (deterministic from
    patient_id sub-seed) but the function call does not mutate any
    global state."""
    rec = CIFPatientRecord()
    rec.icu_transferred = True
    rec.encounters = [
        Encounter(
            encounter_id="enc1",
            encounter_type=EncounterType.INPATIENT,
            admission_datetime=datetime(2026, 1, 1),
            discharge_datetime=datetime(2026, 1, 5),
        )
    ]
    rec.patient.patient_id = "pid_test"
    enrich_device(_Ctx(records=[rec], master_seed=42))
    devs_42 = list(rec.extensions["device"])
    # Reset
    rec.extensions.pop("device", None)
    enrich_device(_Ctx(records=[rec], master_seed=99))
    devs_99 = list(rec.extensions["device"])
    # Device count + ids deterministic by encounter / device type — same
    assert {d.device_id for d in devs_42} == {d.device_id for d in devs_99}
