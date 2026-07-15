"""AD-65 Phase 4 (Task 16): `test-disease --format` + `-o` dev facility.

`clinosim test-disease <disease_id> -n N --format all -o <dir>` runs the full
3-stage pipeline (structural CIF + template narrative + FHIR/CSV export) for a
tiny disease-specific cohort, enabling a ~10-second targeted verify without
regenerating a full cohort. Omitting -o keeps the original stdout debug print.
"""

from __future__ import annotations

import subprocess
import sys

import pytest


@pytest.mark.unit
def test_test_disease_format_all_writes_all_stages(tmp_path):
    out = tmp_path / "verify_mi"
    r = subprocess.run(
        [
            sys.executable,
            "-m",
            "clinosim.simulator.cli",
            "test-disease",
            "acute_mi",
            "-n",
            "3",
            "--format",
            "all",
            "-o",
            str(out),
            "--country",
            "US",
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert r.returncode == 0, r.stderr
    assert (out / "cif" / "structural" / "patients").exists()
    assert (out / "cif" / "narratives" / "template").exists()
    assert (out / "cif" / "narratives" / "current_version.txt").exists()
    assert (out / "fhir_r4" / "Composition.ndjson").exists()
    assert (out / "csv").exists()


@pytest.mark.unit
def test_test_disease_no_output_keeps_stdout(tmp_path):
    r = subprocess.run(
        [
            sys.executable,
            "-m",
            "clinosim.simulator.cli",
            "test-disease",
            "acute_mi",
            "-n",
            "1",
            "--country",
            "US",
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert r.returncode == 0, r.stderr
    # existing debug print — should include patient info
    assert "Patient" in r.stdout or "Chief" in r.stdout
    # no CIF dir since -o not set (default output dir is not implicitly created)
    assert not (tmp_path / "output").exists()


@pytest.mark.unit
def test_test_disease_format_without_output_errors():
    r = subprocess.run(
        [
            sys.executable,
            "-m",
            "clinosim.simulator.cli",
            "test-disease",
            "acute_mi",
            "-n",
            "1",
            "--format",
            "cif",
            "--country",
            "US",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert r.returncode != 0
    assert "--format" in r.stderr and "--output" in r.stderr
