"""Integration: ImagingStudy / Endpoint NDJSON byte-identical across re-runs (AD-16).

Two independent runs with the same seed, country, and population must produce
sha256-identical imaging NDJSON files.  Any RNG leak through the imaging
enricher or builder path would break this invariant.
"""

from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path

import pytest

from tests.integration._sr_helpers import find_ndjson, run_generate


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.integration
def test_imaging_ndjson_byte_identical_us() -> None:
    """Same seed × 2 → identical imaging NDJSON sha256 hashes (US, n=100)."""
    hashes_run1: dict[str, str] = {}
    hashes_run2: dict[str, str] = {}
    for hashes in (hashes_run1, hashes_run2):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out"
            run_generate("US", 100, 42, out)
            for resource in ("ImagingStudy", "Endpoint"):
                hashes[resource] = _sha256(find_ndjson(out, f"{resource}.ndjson"))
    for resource in ("ImagingStudy", "Endpoint"):
        assert hashes_run1[resource] == hashes_run2[resource], (
            f"{resource}.ndjson byte-diff between deterministic re-runs (AD-16)\n"
            f"  run1 sha256={hashes_run1[resource]}\n"
            f"  run2 sha256={hashes_run2[resource]}"
        )


@pytest.mark.integration
def test_imaging_ndjson_byte_identical_jp() -> None:
    """Same seed × 2 → identical imaging NDJSON sha256 hashes (JP, n=200).

    Uses n=200 (not n=100) because JP disease mix at n=100 may not include
    diseases with imaging_orders (bacterial_pneumonia / aspiration_pneumonia /
    hemorrhagic_stroke), causing ImagingStudy.ndjson to be absent.
    """
    hashes_run1: dict[str, str] = {}
    hashes_run2: dict[str, str] = {}
    for hashes in (hashes_run1, hashes_run2):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out"
            run_generate("JP", 200, 42, out)
            # Guard: skip rather than error if no imaging events in this cohort.
            study_files = list(out.rglob("ImagingStudy.ndjson"))
            if not study_files:
                pytest.skip(
                    "No ImagingStudy.ndjson for JP cohort n=200, seed=42. "
                    "Increase population if this fires repeatedly."
                )
            for resource in ("ImagingStudy", "Endpoint"):
                hashes[resource] = _sha256(find_ndjson(out, f"{resource}.ndjson"))
    for resource in ("ImagingStudy", "Endpoint"):
        assert hashes_run1[resource] == hashes_run2[resource], (
            f"{resource}.ndjson byte-diff between deterministic re-runs (AD-16) for JP\n"
            f"  run1 sha256={hashes_run1[resource]}\n"
            f"  run2 sha256={hashes_run2[resource]}"
        )


@pytest.mark.integration
def test_radiology_dr_ndjson_byte_identical() -> None:
    """Radiology DiagnosticReport rows are byte-identical across re-runs (AD-16)."""
    hashes_run1: dict[str, str] = {}
    hashes_run2: dict[str, str] = {}
    for hashes in (hashes_run1, hashes_run2):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out"
            run_generate("US", 100, 42, out)
            hashes["DiagnosticReport"] = _sha256(
                find_ndjson(out, "DiagnosticReport.ndjson")
            )
    assert hashes_run1["DiagnosticReport"] == hashes_run2["DiagnosticReport"], (
        "DiagnosticReport.ndjson byte-diff between deterministic re-runs (AD-16)\n"
        f"  run1 sha256={hashes_run1['DiagnosticReport']}\n"
        f"  run2 sha256={hashes_run2['DiagnosticReport']}"
    )
