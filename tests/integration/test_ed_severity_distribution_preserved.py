"""FP-SEV-MODEL Task 7: ED severity uses the shared categorical primitive.

Distribution-preserving (not byte-identical): the shared primitive normalizes via
normalize_probabilities (numpy float64) vs the old Python-sum, which can flip a
boundary draw by ~1e-17. This smoke test guards that the ED path still runs and
produces encounters after the change.
"""

import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration


def test_ed_cohort_runs_and_produces_encounters(tmp_path):
    out = tmp_path / "out"
    cmd = [
        "python",
        "-m",
        "clinosim.simulator.cli",
        "generate",
        "-p",
        "300",
        "-s",
        "7",
        "--country",
        "US",
        "--format",
        "fhir-r4",
        "-o",
        str(out),
    ]
    proc = subprocess.run(cmd, check=False, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    assert (Path(out) / "fhir_r4" / "Encounter.ndjson").exists()
