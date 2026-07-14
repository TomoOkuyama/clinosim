"""Integration: small ICU cohort produces well-formed Device + DUS NDJSON (PR-A Task 8)."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration


def _read_ndjson(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line]


def test_device_extension_through_fhir_pipeline(tmp_path):
    """A small generated cohort yields well-formed Device + DeviceUseStatement.

    Uses subprocess to exercise the full CLI → enricher → adapter chain.
    p=300 keeps wall-clock under ~30s while practically guaranteeing at
    least one ICU patient (p=200 yielded 8 devices in calibration).
    """
    out = tmp_path / "out"
    cmd = [
        "python", "-m", "clinosim.simulator.cli", "generate",
        "-p", "300", "-s", "42", "--country", "US",
        "--format", "fhir-r4", "-o", str(out),
    ]
    proc = subprocess.run(cmd, check=False, capture_output=True, text=True)
    assert proc.returncode == 0, f"stdout={proc.stdout}\nstderr={proc.stderr}"

    device = _read_ndjson(out / "fhir_r4" / "Device.ndjson")
    dus = _read_ndjson(out / "fhir_r4" / "DeviceUseStatement.ndjson")
    encounter = _read_ndjson(out / "fhir_r4" / "Encounter.ndjson")
    patient = _read_ndjson(out / "fhir_r4" / "Patient.ndjson")

    if not device:
        pytest.skip(
            "p=300 cohort at seed=42 produced 0 ICU transfers this run (rare-event "
            "lottery — device placement requires icu_transferred). Unit tests cover "
            "the placement logic directly; this test only checks the FHIR wiring "
            "once at least one device exists."
        )

    # Session 52 fix 2: facility bundle emits shared Devices without a
    # DeviceUseStatement pair (currently `dev-infusion-pump`, referenced by
    # MedicationAdministration.device for continuous IV infusions per CY8-20).
    # 1:1 applies only to per-patient (ICU) Devices.
    facility_device_ids = {"dev-infusion-pump"}
    patient_devices = [d for d in device if d["id"] not in facility_device_ids]
    assert len(dus) == len(patient_devices), (
        f"per-patient Device count {len(patient_devices)} ≠ "
        f"DeviceUseStatement count {len(dus)}"
    )

    # Referential integrity
    device_ids = {d["id"] for d in device}
    encounter_ids = {e["id"] for e in encounter}
    patient_ids = {p["id"] for p in patient}
    for u in dus:
        d_ref = u["device"]["reference"].split("/", 1)[1]
        assert d_ref in device_ids, f"DUS device ref {d_ref} missing"
        if "context" in u:
            e_ref = u["context"]["reference"].split("/", 1)[1]
            assert e_ref in encounter_ids, f"DUS context ref {e_ref} missing"
        p_ref = u["subject"]["reference"].split("/", 1)[1]
        assert p_ref in patient_ids, f"DUS subject ref {p_ref} missing"

    # Id uniqueness
    assert len(device_ids) == len(device)
    assert len({u["id"] for u in dus}) == len(dus)

    # SNOMED coding shape — per-patient ICU devices (CVC/urinary catheter/
    # ventilator) + facility-shared infusion pump (session 52 fix 2).
    for d in device:
        coding = d["type"]["coding"][0]
        assert coding["code"] in (
            "52124006", "23973005", "706172005", "433296005",
        )
        assert coding["display"] != coding["code"]   # display ≠ code
