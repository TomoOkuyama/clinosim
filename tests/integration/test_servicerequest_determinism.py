"""Integration: ServiceRequest.ndjson is byte-identical across same-seed runs (AD-16).

Two independent runs with the same seed, country, and population must produce
sha256-identical ServiceRequest.ndjson files.  Any RNG leak through the SR
builder path would break this invariant.
"""

import hashlib
import subprocess
import tempfile
from pathlib import Path

import pytest


def _sha256(path: Path) -> str:
    """Return hex SHA-256 digest of path contents."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _run_generate(country: str, n: int, seed: int, out: Path) -> None:
    """Run the full generate pipeline; raise on non-zero exit."""
    subprocess.run(
        [
            "python", "-m", "clinosim.simulator.cli", "generate",
            "--country", country,
            "--population", str(n),
            "--seed", str(seed),
            "--format", "fhir-r4",
            "--output", str(out),
        ],
        check=True,
        capture_output=True,
    )


def _find_ndjson(out: Path, name: str) -> Path:
    """Locate a named NDJSON file anywhere under the output directory."""
    files = list(out.rglob(name))
    assert files, f"{name} not found under {out}"
    return files[0]


@pytest.mark.integration
def test_service_request_ndjson_byte_identical_us():
    """Same seed × 2 → identical ServiceRequest.ndjson sha256 (US, n=50)."""
    hashes: list[str] = []
    for _ in range(2):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out"
            _run_generate("US", 50, 42, out)
            hashes.append(_sha256(_find_ndjson(out, "ServiceRequest.ndjson")))
    assert hashes[0] == hashes[1], (
        f"ServiceRequest.ndjson determinism broken (AD-16):\n"
        f"  run1 sha256={hashes[0]}\n"
        f"  run2 sha256={hashes[1]}"
    )


@pytest.mark.integration
def test_service_request_ndjson_byte_identical_jp():
    """Same seed × 2 → identical ServiceRequest.ndjson sha256 (JP, n=50)."""
    hashes: list[str] = []
    for _ in range(2):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out"
            _run_generate("JP", 50, 42, out)
            hashes.append(_sha256(_find_ndjson(out, "ServiceRequest.ndjson")))
    assert hashes[0] == hashes[1], (
        f"ServiceRequest.ndjson determinism broken (AD-16) for JP:\n"
        f"  run1 sha256={hashes[0]}\n"
        f"  run2 sha256={hashes[1]}"
    )
