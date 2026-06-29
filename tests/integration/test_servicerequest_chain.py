"""Integration tests: ServiceRequest end-to-end (PR1)."""

import json
import subprocess
import tempfile
from pathlib import Path

import pytest

from clinosim.modules.output.fhir_r4_adapter import available_builders


@pytest.mark.integration
def test_service_request_builder_registered():
    """_bb_service_requests must appear in the builder registry after import."""
    builders = available_builders()
    assert "_bb_service_requests" in builders


@pytest.mark.integration
def test_full_pipeline_emits_service_request_no_crash():
    """Verify _bb_service_requests does NOT crash on production-style dict CIF
    (json.load path) and produces a non-empty ServiceRequest.ndjson.

    Uses 'generate --format fhir-r4' so CIF is read back from JSON on disk,
    reproducing the exact production code path that crashed before Fix 1.
    """
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "out"
        result = subprocess.run(
            [
                "python", "-m", "clinosim.simulator.cli", "generate",
                "--country", "US",
                "--population", "5",
                "--seed", "42",
                "--format", "fhir-r4",
                "--output", str(out),
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, (
            f"generate failed (returncode={result.returncode}):\n{result.stderr}"
        )

        # The fhir-r4 output lands in a sub-directory named after the format.
        # Walk for ServiceRequest.ndjson wherever the adapter wrote it.
        sr_files = list(out.rglob("ServiceRequest.ndjson"))
        assert len(sr_files) > 0, (
            "ServiceRequest.ndjson not found under output — builder may not be registered "
            f"or population too small. stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
        sr_file = sr_files[0]
        lines = [ln for ln in sr_file.read_text().splitlines() if ln.strip()]
        assert len(lines) > 0, (
            "ServiceRequest.ndjson is empty — no lab orders were emitted for p=5 cohort"
        )
        # Verify each line is valid JSON with correct resourceType.
        for ln in lines:
            resource = json.loads(ln)
            assert resource["resourceType"] == "ServiceRequest"
            assert resource.get("id", "").startswith("sr-")
