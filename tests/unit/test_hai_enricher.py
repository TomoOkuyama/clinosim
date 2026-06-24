"""Unit tests for clinosim.modules.hai.enricher (PR-B)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import pytest

from clinosim.modules.hai.enricher import enrich_hai
from clinosim.simulator.seeding import ENRICHER_SEED_OFFSETS
from clinosim.types.device import DeviceRecord
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


def test_hai_offset_registered():
    assert ENRICHER_SEED_OFFSETS["hai"] == 0x4841


def test_enrich_hai_empty_records_noop():
    ctx = _Ctx(records=[])
    enrich_hai(ctx)
    assert ctx.records == []


def test_enrich_hai_no_devices_no_hai():
    rec = CIFPatientRecord()
    rec.patient.patient_id = "pid_test"
    ctx = _Ctx(records=[rec])
    enrich_hai(ctx)
    assert "hai" not in rec.extensions


def test_enrich_hai_with_device_long_period_emits_hai():
    """Device with very long line-days → cumulative probability → some HAI(s)."""
    rec = CIFPatientRecord()
    rec.patient.patient_id = "pid_test"
    rec.icu_transferred = True
    rec.encounters = [
        Encounter(
            encounter_id="enc1",
            encounter_type=EncounterType.INPATIENT,
            admission_datetime=datetime(2026, 1, 1),
            discharge_datetime=datetime(2026, 12, 31),
        ),
    ]
    rec.extensions["device"] = [
        DeviceRecord(
            device_id="dev-enc1-cvc-0", encounter_id="enc1",
            device_type="cvc", snomed_code="52124006",
            placement_date="2026-01-01", removal_date="2026-12-31",
            placement_indication="severity_moderate_plus",
        ),
        DeviceRecord(
            device_id="dev-enc1-indwelling_catheter-0", encounter_id="enc1",
            device_type="indwelling_catheter", snomed_code="23973005",
            placement_date="2026-01-01", removal_date="2026-12-31",
            placement_indication="severity_moderate_plus",
        ),
        DeviceRecord(
            device_id="dev-enc1-mechanical_ventilator-0", encounter_id="enc1",
            device_type="mechanical_ventilator", snomed_code="706172005",
            placement_date="2026-01-01", removal_date="2026-12-31",
            placement_indication="hypoxia",
        ),
    ]
    ctx = _Ctx(records=[rec], master_seed=42)
    enrich_hai(ctx)
    assert "hai" in rec.extensions
    assert len(rec.extensions["hai"]) >= 1
    device_ids = {d.device_id for d in rec.extensions["device"]}
    for h in rec.extensions["hai"]:
        assert h.source_device_id in device_ids
    assert len(rec.microbiology) >= len(rec.extensions["hai"])


def test_enrich_hai_unknown_device_type_skipped():
    """Devices with no HAI mapping (e.g. peripheral IV) are skipped."""
    rec = CIFPatientRecord()
    rec.patient.patient_id = "pid_test"
    rec.icu_transferred = True
    rec.encounters = [
        Encounter(
            encounter_id="enc1",
            encounter_type=EncounterType.INPATIENT,
            admission_datetime=datetime(2026, 1, 1),
            discharge_datetime=datetime(2026, 12, 31),
        ),
    ]
    rec.extensions["device"] = [
        DeviceRecord(
            device_id="dev-enc1-piv-0", encounter_id="enc1",
            device_type="peripheral_iv", snomed_code="000000",
            placement_date="2026-01-01", removal_date="2026-12-31",
            placement_indication="",
        ),
    ]
    ctx = _Ctx(records=[rec], master_seed=42)
    enrich_hai(ctx)
    assert "hai" not in rec.extensions or rec.extensions.get("hai") == []


def test_enrich_hai_sub_seed_deterministic():
    """Same patient + same seed → same HAI set across runs."""
    def make_rec():
        rec = CIFPatientRecord()
        rec.patient.patient_id = "pid_test"
        rec.icu_transferred = True
        rec.encounters = [
            Encounter(
                encounter_id="enc1",
                encounter_type=EncounterType.INPATIENT,
                admission_datetime=datetime(2026, 1, 1),
                discharge_datetime=datetime(2026, 12, 31),
            ),
        ]
        rec.extensions["device"] = [
            DeviceRecord(
                device_id="dev-enc1-cvc-0", encounter_id="enc1",
                device_type="cvc", snomed_code="52124006",
                placement_date="2026-01-01", removal_date="2026-12-31",
                placement_indication="severity_moderate_plus",
            ),
        ]
        return rec

    rec1 = make_rec()
    enrich_hai(_Ctx(records=[rec1], master_seed=42))
    rec2 = make_rec()
    enrich_hai(_Ctx(records=[rec2], master_seed=42))
    ids_1 = sorted(h.hai_id for h in rec1.extensions.get("hai", []))
    ids_2 = sorted(h.hai_id for h in rec2.extensions.get("hai", []))
    assert ids_1 == ids_2
