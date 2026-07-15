"""Integration: ServiceRequest.ndjson is byte-identical across same-seed runs (AD-16).

Two independent runs with the same seed, country, and population must produce
sha256-identical ServiceRequest.ndjson files.  Any RNG leak through the SR
builder path would break this invariant.
"""

import hashlib
import tempfile
from pathlib import Path

import pytest

from tests.integration._sr_helpers import find_ndjson, run_generate


def _sha256(path: Path) -> str:
    """Return hex SHA-256 digest of path contents."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.integration
def test_service_request_ndjson_byte_identical_us():
    """Same seed × 2 → identical ServiceRequest.ndjson sha256 (US, n=50)."""
    hashes: list[str] = []
    for _ in range(2):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out"
            run_generate("US", 50, 42, out)
            hashes.append(_sha256(find_ndjson(out, "ServiceRequest.ndjson")))
    assert hashes[0] == hashes[1], (
        f"ServiceRequest.ndjson determinism broken (AD-16):\n  run1 sha256={hashes[0]}\n  run2 sha256={hashes[1]}"
    )


@pytest.mark.integration
def test_service_request_ndjson_byte_identical_jp():
    """Same seed × 2 → identical ServiceRequest.ndjson sha256 (JP, n=50)."""
    hashes: list[str] = []
    for _ in range(2):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out"
            run_generate("JP", 50, 42, out)
            hashes.append(_sha256(find_ndjson(out, "ServiceRequest.ndjson")))
    assert hashes[0] == hashes[1], (
        f"ServiceRequest.ndjson determinism broken (AD-16) for JP:\n"
        f"  run1 sha256={hashes[0]}\n"
        f"  run2 sha256={hashes[1]}"
    )
