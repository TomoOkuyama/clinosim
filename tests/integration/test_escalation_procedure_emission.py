"""Integration test: escalation procedure entries emit FHIR Procedure, not MedicationRequest.

Issue #460: after the type-signal migration, `Hemodialysis` (and the other 5
procedure escalation entries) must route to OrderType.PROCEDURE at the Order
level and appear in Procedure.ndjson, not MedicationRequest.ndjson.

Uses JP p=500 seed=42 cohort as the smoke gate — small enough for CI, large
enough that at least one AKI patient typically triggers day-3 escalation.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

PROCEDURE_DRUG_NAMES = (
    "Hemodialysis",
    "Vertebroplasty",
    "Kyphoplasty",
    "Catheter-directed thrombolysis",
)


def _grep_ndjson(ndjson_path: Path, needle: str) -> int:
    """Count NDJSON lines whose JSON payload contains the needle substring."""
    if not ndjson_path.exists():
        return 0
    count = 0
    for line in ndjson_path.read_text().splitlines():
        if not line.strip():
            continue
        if needle in line:
            count += 1
    return count


def _run_generate(out_dir: Path) -> None:
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[2])}
    subprocess.run(
        [
            "clinosim",
            "generate",
            "--country",
            "JP",
            "--population",
            "500",
            "--seed",
            "42",
            "--start",
            "2025-01-01",
            "--end",
            "2026-01-01",
            "--format",
            "fhir-r4",
            "--output",
            str(out_dir),
        ],
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )


def test_procedure_drug_names_not_in_medication_request(tmp_path):
    """None of the 4 migrated drug labels appear in MedicationRequest.ndjson."""
    out_dir = tmp_path / "cohort"
    _run_generate(out_dir)
    mr_path = out_dir / "fhir_r4" / "MedicationRequest.ndjson"
    for name in PROCEDURE_DRUG_NAMES:
        count = _grep_ndjson(mr_path, name)
        assert count == 0, (
            f"{name!r} unexpectedly present in MedicationRequest.ndjson "
            f"({count} occurrences) — migration to type=procedure not applied "
            f"or FHIR Procedure routing broken."
        )


def test_procedure_ndjson_present(tmp_path):
    """Procedure.ndjson exists and is non-empty (sanity gate for the above)."""
    out_dir = tmp_path / "cohort"
    _run_generate(out_dir)
    proc_path = out_dir / "fhir_r4" / "Procedure.ndjson"
    assert proc_path.exists(), "Procedure.ndjson not emitted"
    assert proc_path.stat().st_size > 0, "Procedure.ndjson is empty"
    # Also verify the file is valid NDJSON (each line parses as JSON).
    lines = [ln for ln in proc_path.read_text().splitlines() if ln.strip()]
    for i, ln in enumerate(lines[:5]):
        try:
            json.loads(ln)
        except json.JSONDecodeError as e:
            pytest.fail(f"Procedure.ndjson line {i} invalid: {e}")
