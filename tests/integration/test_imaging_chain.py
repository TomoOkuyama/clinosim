"""Integration tests: imaging chain end-to-end emission (Tier 1 #2).

Verifies that a full run-beta pipeline emits the 4 imaging resource types
(ServiceRequest/imaging, ImagingStudy, Endpoint, DiagnosticReport/radiology)
and that the 1:1 ImagingStudy : Endpoint invariant holds.
"""

from __future__ import annotations

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
    """1:1 invariant between non-stub ImagingStudy and Endpoint.

    Session 52 fix 3: stub-only studies (inference failed; no modality, no
    series) intentionally carry no PACS Endpoint (session 48 case D), so the
    invariant is scoped to studies that declare an endpoint reference.
    Stub studies must NOT reference an Endpoint, and no Endpoint may have an
    empty id.
    """
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "out"
        run_generate("US", 200, 42, out)
        studies = load_ndjson(find_ndjson(out, "ImagingStudy.ndjson"))
        endpoints = load_ndjson(find_ndjson(out, "Endpoint.ndjson"))
        if not studies:
            pytest.skip("No ImagingStudy resources emitted for n=200 cohort")
        assert all(e.get("id") for e in endpoints), (
            "Endpoint with empty id emitted (stub studies must not emit Endpoints)"
        )
        non_stub = [s for s in studies if s.get("modality")]
        stubs = [s for s in studies if not s.get("modality")]
        for s in stubs:
            assert not s.get("endpoint"), (
                f"stub ImagingStudy/{s['id']} must not reference an Endpoint"
            )
        assert len(non_stub) == len(endpoints), (
            f"non-stub ImagingStudy count {len(non_stub)} != Endpoint count "
            f"{len(endpoints)} (1:1 invariant broken)"
        )


@pytest.mark.integration
def test_imaging_stub_share_bounded() -> None:
    """Stub (inference-failed) studies must stay a small minority.

    Silent-no-op defense: a regression in `infer_imaging_metadata` or
    modalities.yaml would silently degrade studies to text-only stubs;
    this bound catches a coverage collapse. Known residual stubs are
    non-DICOM orders (Bladder_ultrasound / Slit_lamp_exam / Fluorescein_stain)
    at ~2% of the n=200 cohort.
    """
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "out"
        run_generate("US", 200, 42, out)
        studies = load_ndjson(find_ndjson(out, "ImagingStudy.ndjson"))
        if not studies:
            pytest.skip("No ImagingStudy resources emitted for n=200 cohort")
        stubs = [s for s in studies if not s.get("modality")]
        share = len(stubs) / len(studies)
        assert share <= 0.15, (
            f"stub ImagingStudy share {share:.1%} ({len(stubs)}/{len(studies)}) "
            "exceeds 15% — imaging inference coverage regressed"
        )


@pytest.mark.integration
def test_radiology_dr_count_equals_imaging_study_count() -> None:
    """Radiology DiagnosticReports map 1:1 into ImagingStudies.

    Session 52 fix 3: not every study carries a report (stub studies never
    do; non-stub studies from the ED / unknown-condition path emit
    report=None when no impression template is registered — session 48
    case D). The retained invariant: every radiology DR corresponds to
    exactly one ImagingStudy via the shared ``{encounter_id}-{idx}`` id
    suffix, and studies with reports are a non-empty subset.
    """
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "out"
        run_generate("US", 200, 42, out)
        studies = load_ndjson(find_ndjson(out, "ImagingStudy.ndjson"))
        if not studies:
            pytest.skip("No ImagingStudy resources emitted for n=200 cohort")
        drs = load_ndjson(find_ndjson(out, "DiagnosticReport.ndjson"))
        rad_drs = [r for r in drs if r.get("id", "").startswith("imgrpt-")]
        assert rad_drs, "no radiology DiagnosticReport emitted at all"
        study_suffixes = {s["id"].removeprefix("imgst-") for s in studies}
        dr_suffixes = [r["id"].removeprefix("imgrpt-") for r in rad_drs]
        orphans = [sfx for sfx in dr_suffixes if sfx not in study_suffixes]
        assert not orphans, (
            f"{len(orphans)} radiology DRs without matching ImagingStudy: {orphans[:5]}"
        )
        assert len(dr_suffixes) == len(set(dr_suffixes)), (
            "duplicate radiology DR ids — 1:1 injectivity broken"
        )
        assert len(rad_drs) <= len(studies)


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
