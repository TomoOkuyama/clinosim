"""Integration tests: imaging chain end-to-end emission (Tier 1 #2).

Verifies that a full run-beta pipeline emits the 4 imaging resource types
(ServiceRequest/imaging, ImagingStudy, Endpoint, DiagnosticReport/radiology)
and that the 1:1 ImagingStudy : Endpoint invariant holds.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from clinosim.modules.output.fhir_r4_adapter import available_builders
from tests.integration._sr_helpers import find_ndjson, load_ndjson, run_generate


@pytest.mark.integration
def test_imaging_builders_registered() -> None:
    """_bb_imaging_studies and _bb_endpoints must appear in the builder registry."""
    builders = available_builders()
    assert "_bb_imaging_studies" in builders, (
        "_bb_imaging_studies not registered — check fhir_r4_adapter.py imports"
    )
    assert "_bb_endpoints" in builders, (
        "_bb_endpoints not registered — check fhir_r4_adapter.py imports"
    )


@pytest.mark.integration
def test_us_cohort_emits_4_imaging_resource_types() -> None:
    """All 4 imaging-related NDJSON files must exist and be non-empty."""
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "out"
        run_generate("US", 200, 42, out)
        for resource in ("ServiceRequest", "ImagingStudy", "DiagnosticReport", "Endpoint"):
            f = find_ndjson(out, f"{resource}.ndjson")
            assert f.exists(), f"{resource}.ndjson missing"
            assert f.stat().st_size > 0, f"{resource}.ndjson empty"


@pytest.mark.integration
def test_imaging_study_count_matches_endpoint_count() -> None:
    """1:1 invariant: every ImagingStudy has exactly one Endpoint."""
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "out"
        run_generate("US", 200, 42, out)
        studies = load_ndjson(find_ndjson(out, "ImagingStudy.ndjson"))
        endpoints = load_ndjson(find_ndjson(out, "Endpoint.ndjson"))
        if not studies:
            pytest.skip("No ImagingStudy resources emitted for n=200 cohort")
        assert len(studies) == len(endpoints), (
            f"ImagingStudy count {len(studies)} != Endpoint count {len(endpoints)} "
            "(1:1 invariant broken)"
        )


@pytest.mark.integration
def test_radiology_dr_count_equals_imaging_study_count() -> None:
    """Every ImagingStudy must have a corresponding radiology DiagnosticReport (1:1)."""
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "out"
        run_generate("US", 200, 42, out)
        studies = load_ndjson(find_ndjson(out, "ImagingStudy.ndjson"))
        if not studies:
            pytest.skip("No ImagingStudy resources emitted for n=200 cohort")
        drs = load_ndjson(find_ndjson(out, "DiagnosticReport.ndjson"))
        rad_drs = [r for r in drs if r.get("id", "").startswith("imgrpt-")]
        assert len(rad_drs) == len(studies), (
            f"Radiology DiagnosticReport count {len(rad_drs)} "
            f"!= ImagingStudy count {len(studies)} — 1:1 invariant broken"
        )


@pytest.mark.integration
def test_imaging_sr_emitted_for_disease_cohort() -> None:
    """ServiceRequest.ndjson must contain at least one imaging-category SR."""
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "out"
        run_generate("US", 200, 42, out)
        srs = load_ndjson(find_ndjson(out, "ServiceRequest.ndjson"))
        imaging_srs = [
            s for s in srs
            if any(
                c.get("code") in {"363679005", "RAD"}
                for entry in s.get("category", [])
                for c in entry.get("coding", [])
            )
        ]
        assert imaging_srs, (
            "No imaging ServiceRequests (363679005 / RAD category) found in "
            "ServiceRequest.ndjson for n=200 cohort. Imaging enricher may not be "
            "firing for any disease in this cohort."
        )
