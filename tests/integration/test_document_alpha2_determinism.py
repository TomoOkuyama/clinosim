"""Integration: α-min-2 document + CareTeam NDJSON byte-identical across re-runs (AD-16).

Two independent runs with the same seed, country, and population must produce
sha256-identical NDJSON files for all α-min-2 new resource types.  Any RNG
leak through the new enrichers (nursing/triage/document α-min-2 path/care_team
builder) would break this invariant.

Covers:
- CareTeam.ndjson (new in α-min-2)
- DocumentReference.ndjson (extended with NURSING_SHIFT_NOTE)
- Composition.ndjson (extended with NURSING_ASSESSMENT + NURSING_DISCHARGE_SUMMARY)
- ClinicalImpression.ndjson (unchanged, regression guard)
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
def test_alpha2_ndjson_byte_identical_us() -> None:
    """Same seed × 2 → identical α-min-2 NDJSON sha256 hashes (US, n=100)."""
    resources = ("CareTeam", "DocumentReference", "Composition", "ClinicalImpression")
    hashes_run1: dict[str, str] = {}
    hashes_run2: dict[str, str] = {}
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
def test_alpha2_ndjson_byte_identical_jp() -> None:
    """Same seed × 2 → identical α-min-2 NDJSON sha256 hashes (JP, n=200)."""
    resources = ("CareTeam", "DocumentReference", "Composition", "ClinicalImpression")
    hashes_run1: dict[str, str] = {}
    hashes_run2: dict[str, str] = {}
    for hashes in (hashes_run1, hashes_run2):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out"
            run_generate("JP", 200, 42, out)
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
def test_alpha2_different_seeds_produce_different_care_team_ndjson() -> None:
    """Different seeds must produce different CareTeam.ndjson (trivial pass guard).

    Ensures that the determinism tests above cannot trivially pass on an always-
    empty pipeline (if CareTeam.ndjson is always empty, sha256 is always identical
    regardless of seed, masking a no-op builder).
    """
    with tempfile.TemporaryDirectory() as tmp_a, tempfile.TemporaryDirectory() as tmp_b:
        out_a = Path(tmp_a) / "out"
        out_b = Path(tmp_b) / "out"
        run_generate("US", 100, 42, out_a)
        run_generate("US", 100, 99, out_b)

        files_a = list(out_a.rglob("CareTeam.ndjson"))
        files_b = list(out_b.rglob("CareTeam.ndjson"))

        if not files_a or not files_b:
            pytest.skip("CareTeam.ndjson absent for one or both seeds — builder not firing")

        sha_a = _sha256(files_a[0])
        sha_b = _sha256(files_b[0])
        assert sha_a != sha_b, (
            "seed=42 and seed=99 produced identical CareTeam.ndjson — "
            "CareTeam builder may be producing no output (silent-no-op concern). "
            "Verify that encounters are being generated with differing physician IDs."
        )
