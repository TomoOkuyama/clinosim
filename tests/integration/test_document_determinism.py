"""Integration: document-chain NDJSON byte-identical across re-runs (AD-16).

Two independent runs with the same seed, country, and population must produce
sha256-identical document-chain NDJSON files.  Any RNG leak through the
document enricher or builder path would break this invariant.

Covers: DocumentReference, Composition, ClinicalImpression, AllergyIntolerance.
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
def test_document_ndjson_byte_identical_us() -> None:
    """Same seed × 2 → identical document NDJSON sha256 hashes (US, n=100)."""
    hashes_run1: dict[str, str] = {}
    hashes_run2: dict[str, str] = {}
    resources = ("DocumentReference", "Composition", "ClinicalImpression", "AllergyIntolerance")
    for hashes in (hashes_run1, hashes_run2):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out"
            run_generate("US", 100, 42, out)
            for resource in resources:
                hashes[resource] = _sha256(find_ndjson(out, f"{resource}.ndjson"))
    for resource in resources:
        assert hashes_run1[resource] == hashes_run2[resource], (
            f"{resource}.ndjson byte-diff between deterministic re-runs (AD-16)\n"
            f"  run1 sha256={hashes_run1[resource]}\n"
            f"  run2 sha256={hashes_run2[resource]}"
        )


@pytest.mark.integration
def test_document_ndjson_byte_identical_jp() -> None:
    """Same seed × 2 → identical document NDJSON sha256 hashes (JP, n=200)."""
    hashes_run1: dict[str, str] = {}
    hashes_run2: dict[str, str] = {}
    resources = ("DocumentReference", "Composition", "ClinicalImpression", "AllergyIntolerance")
    for hashes in (hashes_run1, hashes_run2):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out"
            run_generate("JP", 200, 42, out)
            # Guard: skip if a resource is absent (rare-event safety).
            for resource in resources:
                ndjson_files = list(out.rglob(f"{resource}.ndjson"))
                if not ndjson_files:
                    pytest.skip(
                        f"{resource}.ndjson absent for JP cohort n=200, seed=42. "
                        "Increase population if this fires repeatedly."
                    )
                hashes[resource] = _sha256(ndjson_files[0])
    for resource in resources:
        assert hashes_run1[resource] == hashes_run2[resource], (
            f"{resource}.ndjson byte-diff between deterministic re-runs (AD-16) for JP\n"
            f"  run1 sha256={hashes_run1[resource]}\n"
            f"  run2 sha256={hashes_run2[resource]}"
        )


@pytest.mark.integration
def test_different_seeds_produce_different_ndjson() -> None:
    """Different seeds must produce at least one differing NDJSON (smoke test).

    Ensures that the determinism tests above cannot trivially pass on an always-
    empty pipeline (if DocumentReference.ndjson is always empty, sha256 is
    always identical regardless of seed, masking a no-op enricher).
    """
    hashes_seed42: dict[str, str] = {}
    hashes_seed99: dict[str, str] = {}
    for seed, hashes in ((42, hashes_seed42), (99, hashes_seed99)):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out"
            run_generate("US", 100, seed, out)
            for resource in ("DocumentReference", "ClinicalImpression"):
                ndjson_files = list(out.rglob(f"{resource}.ndjson"))
                if ndjson_files:
                    hashes[resource] = hashes_seed42.get(resource, "") or (
                        hashes[resource] if resource in hashes else
                        hashes_seed42.get(resource, "__absent__")
                    )
    # At least one resource must differ across seeds (trivial pass guard).
    # (Both runs must produce the resource for this check to be meaningful.)
    differences = 0
    with tempfile.TemporaryDirectory() as tmp_a, tempfile.TemporaryDirectory() as tmp_b:
        out_a = Path(tmp_a) / "out"
        out_b = Path(tmp_b) / "out"
        run_generate("US", 100, 42, out_a)
        run_generate("US", 100, 99, out_b)
        for resource in ("DocumentReference", "ClinicalImpression"):
            files_a = list(out_a.rglob(f"{resource}.ndjson"))
            files_b = list(out_b.rglob(f"{resource}.ndjson"))
            if files_a and files_b:
                if _sha256(files_a[0]) != _sha256(files_b[0]):
                    differences += 1
    assert differences >= 1, (
        "seed=42 and seed=99 produced identical DocumentReference.ndjson and "
        "ClinicalImpression.ndjson — enricher may be determinism-locked but also "
        "producing no output (silent-no-op concern). Investigate."
    )
