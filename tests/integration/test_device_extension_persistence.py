"""Integration: DeviceRecord serializable; CIF extensions round-trip (PR-A Task 8)."""
from __future__ import annotations

import json
from dataclasses import asdict

import pytest

from clinosim.types.device import DeviceRecord
from clinosim.types.output import CIFPatientRecord


pytestmark = pytest.mark.integration


def test_device_record_serializable_via_asdict():
    rec = DeviceRecord(
        device_id="dev-enc1-cvc-0",
        encounter_id="enc1",
        device_type="cvc",
        snomed_code="52124006",
        placement_date="2026-01-01",
        removal_date="2026-01-08",
        placement_indication="severity_moderate_plus",
    )
    d = asdict(rec)
    assert d["device_id"] == "dev-enc1-cvc-0"
    assert d["snomed_code"] == "52124006"
    assert d["removal_date"] == "2026-01-08"


def test_cif_patient_record_extensions_round_trip(tmp_path):
    rec = CIFPatientRecord()
    rec.extensions["device"] = [
        DeviceRecord(
            device_id="dev-e1-cvc-0",
            encounter_id="e1",
            device_type="cvc",
            snomed_code="52124006",
            placement_date="2026-01-01",
            removal_date="2026-01-08",
            placement_indication="severity_moderate_plus",
        ),
    ]
    serialised = {
        "extensions": {
            "device": [asdict(d) for d in rec.extensions["device"]],
        }
    }
    path = tmp_path / "rec.json"
    path.write_text(json.dumps(serialised))

    loaded = json.loads(path.read_text())
    assert loaded["extensions"]["device"][0]["snomed_code"] == "52124006"
    assert loaded["extensions"]["device"][0]["removal_date"] == "2026-01-08"
    assert loaded["extensions"]["device"][0]["device_type"] == "cvc"
