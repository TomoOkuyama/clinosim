"""End-to-end reproducibility gate (P1-7, session 46).

Runs ``scripts/reproduce.sh`` as a subprocess and asserts exit 0. The
script itself generates two independent runs per locale (US + JP by
default) at the same seed and diffs every output file byte-for-byte,
excluding wall-clock metadata (``manifest.json`` + ``cif/metadata.json``).

This is the enforcement side of the SemVer determinism promise
recorded in ``CHANGELOG.md``: within one MINOR release line, the same
``(seed, config, country, start, end, population)`` tuple produces
byte-identical output.

Marked ``integration`` because a full run takes ~30 s per locale on a
warm interpreter — unit-suite budget is <60 s total.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO_ROOT / "scripts" / "reproduce.sh"


@pytest.mark.integration
def test_reproduce_script_passes() -> None:
    """``scripts/reproduce.sh`` must exit 0 (byte-identical output on
    US + JP at seed 42 with pop 50, 2026-01-01 → 2026-03-31)."""
    assert _SCRIPT.exists(), f"reproduce script missing at {_SCRIPT}"
    assert _SCRIPT.stat().st_mode & 0o111, (
        f"reproduce script at {_SCRIPT} is not executable — run `chmod +x scripts/reproduce.sh`."
    )

    result = subprocess.run(
        [str(_SCRIPT)],
        capture_output=True,
        text=True,
        cwd=_REPO_ROOT,
        timeout=600,  # 10 min — script measures ~60 s locally, cushion for CI runners
    )

    # The script prints its own diff on failure, so surface both streams to
    # pytest -v output for easy diagnosis.
    if result.returncode != 0:
        pytest.fail(
            f"scripts/reproduce.sh exited {result.returncode}\n"
            f"--- stdout ---\n{result.stdout}\n"
            f"--- stderr ---\n{result.stderr}"
        )
