"""AD-65 Phase 4 (Task 17): `test-encounter --format` + `-o` dev facility.

`clinosim test-encounter <condition_id> -n N --format all -o <dir>` runs the full
3-stage pipeline (structural CIF + template narrative + FHIR/CSV export) for a tiny
encounter-specific cohort, enabling a ~10-second targeted verify without regenerating
a full cohort. Omitting -o keeps the original stdout debug print.
"""

from __future__ import annotations

import subprocess
import sys

import pytest


@pytest.mark.unit
def test_test_encounter_format_all_writes_all_stages(tmp_path):
    out = tmp_path / "verify_ed"
    r = subprocess.run(
        [
            sys.executable, "-m", "clinosim.simulator.cli", "test-encounter",
            "chest_pain_noncardiac", "-n", "3", "--format", "all", "-o", str(out),
            "--country", "US",
        ],
        capture_output=True, text=True, timeout=120,
    )
    assert r.returncode == 0, r.stderr
    assert (out / "cif" / "structural" / "patients").exists()
    assert (out / "cif" / "narratives" / "template").exists()
    assert (out / "cif" / "narratives" / "current_version.txt").exists()
    # ED/outpatient encounters don't produce Composition (inpatient-only).
    # Check that FHIR and CSV exports were created.
    assert (out / "fhir_r4").is_dir()
    assert list((out / "fhir_r4").glob("*.ndjson"))
    assert (out / "csv").exists()


@pytest.mark.unit
def test_test_encounter_no_output_keeps_stdout(tmp_path):
    r = subprocess.run(
        [
            sys.executable, "-m", "clinosim.simulator.cli", "test-encounter",
            "chest_pain_noncardiac", "-n", "1", "--country", "US",
        ],
        capture_output=True, text=True, timeout=60,
    )
    assert r.returncode == 0, r.stderr
    # existing debug print — should include patient info
    assert "Patient" in r.stdout or "Chief" in r.stdout
    # no CIF dir since -o not set (default output dir is not implicitly created)
    assert not (tmp_path / "output").exists()


@pytest.mark.unit
def test_test_encounter_format_without_output_errors():
    r = subprocess.run(
        [
            sys.executable, "-m", "clinosim.simulator.cli", "test-encounter",
            "chest_pain_noncardiac", "-n", "1", "--format", "cif", "--country", "US",
        ],
        capture_output=True, text=True, timeout=30,
    )
    assert r.returncode != 0
    assert "--format" in r.stderr and "--output" in r.stderr


@pytest.mark.unit
def test_test_encounter_outpatient_condition(tmp_path):
    """Test with an outpatient encounter condition."""
    out = tmp_path / "verify_outpatient"
    r = subprocess.run(
        [
            sys.executable, "-m", "clinosim.simulator.cli", "test-encounter",
            "flu_vaccination", "-n", "2", "--format", "cif", "-o", str(out),
            "--country", "US",
        ],
        capture_output=True, text=True, timeout=120,
    )
    assert r.returncode == 0, r.stderr
    assert (out / "cif" / "structural" / "patients").exists()
    assert (out / "cif" / "narratives" / "current_version.txt").exists()
