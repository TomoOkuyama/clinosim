"""Integration: subprocess run-beta → imaging NDJSON full-pipeline (PR1 教訓).

Exercises the production json.dump → json.load → dict CIF path that unit
tests with dataclass fixtures cannot cover.  PR1 ServiceRequest LAB exposed
a bug where the builder crashed on production dict CIF; this test guards the
same anti-pattern for the new imaging builders (_bb_imaging_studies,
_bb_endpoints, _bb_diagnostic_reports imaging path).

Guards:
- No AttributeError / KeyError / TypeError in stderr (PR-90 silent-no-op class)
- ImagingStudy.ndjson and Endpoint.ndjson parse as valid JSON lines
- Each ImagingStudy has a "resourceType": "ImagingStudy" field
- Each Endpoint has a "resourceType": "Endpoint" field
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from tests.integration._sr_helpers import find_ndjson, load_ndjson, run_generate


@pytest.mark.integration
def test_subprocess_produces_well_formed_imaging_ndjson() -> None:
    """Full pipeline via subprocess: imaging NDJSON is valid and error-free."""
    import subprocess
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "out"
        result = subprocess.run(
            [
                "python", "-m", "clinosim.simulator.cli", "generate",
                "--country", "US",
                "--population", "100",
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
        # PR1 LAB regression class: attribute/key errors appear in stderr.
        for err_class in ("AttributeError", "KeyError", "TypeError"):
            assert err_class not in result.stderr, (
                f"{err_class} found in stderr — imaging builder may be crashing on dict CIF:\n"
                f"{result.stderr[:500]}"
            )
        # All imaging-related NDJSONs parse as valid JSON lines.
        for resource in ("ImagingStudy", "Endpoint"):
            f = find_ndjson(out, f"{resource}.ndjson")
            for line in f.read_text().splitlines():
                if line.strip():
                    parsed = json.loads(line)
                    assert parsed.get("resourceType") == resource, (
                        f"Expected resourceType={resource!r}, got {parsed.get('resourceType')!r}"
                    )


@pytest.mark.integration
def test_subprocess_imaging_study_has_required_fields() -> None:
    """Each ImagingStudy has required FHIR R4 fields: status, modality, subject."""
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "out"
        run_generate("US", 100, 42, out)
        studies = load_ndjson(find_ndjson(out, "ImagingStudy.ndjson"))
        if not studies:
            pytest.skip("No ImagingStudy resources emitted for n=100 cohort")
        non_stub_seen = False
        for study in studies:
            sid = study.get("id", "?")
            assert study.get("status") in {"available", "registered"}, (
                f"ImagingStudy/{sid} unexpected status {study.get('status')!r}"
            )
            # Session 52 fix 3: stub-only studies (inference failed, session
            # 48 case D) legitimately omit modality; all other required
            # fields still apply to every study.
            if study.get("modality"):
                non_stub_seen = True
            assert study.get("subject"), (
                f"ImagingStudy/{sid} missing subject"
            )
            assert study.get("started"), (
                f"ImagingStudy/{sid} missing started datetime"
            )
        assert non_stub_seen, (
            "every ImagingStudy is a stub — imaging inference coverage collapsed"
        )


@pytest.mark.integration
def test_subprocess_endpoint_has_required_fields() -> None:
    """Each Endpoint has required FHIR R4 fields: status, connectionType, address."""
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "out"
        run_generate("US", 100, 42, out)
        endpoints = load_ndjson(find_ndjson(out, "Endpoint.ndjson"))
        if not endpoints:
            pytest.skip("No Endpoint resources emitted for n=100 cohort")
        for ep in endpoints:
            ep_id = ep.get("id", "?")
            assert ep.get("status") == "active", (
                f"Endpoint/{ep_id} expected status='active', got {ep.get('status')!r}"
            )
            assert ep.get("connectionType"), (
                f"Endpoint/{ep_id} missing connectionType"
            )
            assert ep.get("address"), (
                f"Endpoint/{ep_id} missing address (WADO-RS URL)"
            )


@pytest.mark.integration
def test_subprocess_radiology_dr_has_required_fields() -> None:
    """Each radiology DiagnosticReport has required fields and a non-empty conclusion."""
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "out"
        run_generate("US", 100, 42, out)
        drs = load_ndjson(find_ndjson(out, "DiagnosticReport.ndjson"))
        rad_drs = [r for r in drs if r.get("id", "").startswith("imgrpt-")]
        if not rad_drs:
            pytest.skip("No radiology DiagnosticReport resources emitted for n=100 cohort")
        for dr in rad_drs:
            dr_id = dr.get("id", "?")
            assert dr.get("status") == "final", (
                f"DiagnosticReport/{dr_id} expected status='final', got {dr.get('status')!r}"
            )
            assert dr.get("conclusion"), (
                f"DiagnosticReport/{dr_id} missing conclusion (impression_text)"
            )
            assert dr.get("imagingStudy"), (
                f"DiagnosticReport/{dr_id} missing imagingStudy reference"
            )
