"""Shared helpers for ServiceRequest integration tests.

Extracted from individual test modules to avoid 4-way duplication of
_run_generate / _find_ndjson / _load_ndjson (Minor 3, Task 9 review).
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any


def run_generate(
    country: str,
    n: int,
    seed: int,
    out: Path,
    *,
    end: str | None = None,
) -> None:
    """Run ``clinosim generate --format fhir-r4`` and assert exit 0.

    When ``end`` is provided without ``--start``, the CLI defaults start to
    (end - 1 year), producing a full-year cohort truncated at the snapshot.
    """
    cmd = [
        "python",
        "-m",
        "clinosim.simulator.cli",
        "generate",
        "--country",
        country,
        "--population",
        str(n),
        "--seed",
        str(seed),
        "--format",
        "fhir-r4",
        "--output",
        str(out),
    ]
    if end:
        cmd += ["--end", end]
    result = subprocess.run(cmd, capture_output=True, text=True)
    assert result.returncode == 0, f"generate failed (returncode={result.returncode}):\n{result.stderr}"


def find_ndjson(out: Path, name: str) -> Path:
    """Recursively locate a named NDJSON file under the output directory."""
    files = list(out.rglob(name))
    assert files, f"{name} not found under {out}"
    return files[0]


def load_ndjson(path: Path) -> list[dict[str, Any]]:
    """Load all non-empty NDJSON lines from *path*."""
    with path.open() as f:
        return [json.loads(line) for line in f if line.strip()]
