"""Integration: subprocess run-beta → α-min-2 document NDJSON full-pipeline (PR-90 教訓).

Exercises the production json.dump → json.load → dict CIF path that unit tests
with dataclass fixtures cannot cover.  PR1 ServiceRequest LAB exposed a bug
where the builder crashed on production dict CIF; this test guards the same
anti-pattern for the new α-min-2 builders:
  _bb_care_teams, and the α-min-2 extended _bb_document_references +
  _bb_compositions (nursing types).

Guards:
- No AttributeError / KeyError / TypeError in stderr (PR-90 silent-no-op class)
- CareTeam.ndjson exists and is non-empty
- DocumentReference.ndjson includes NURSING_SHIFT_NOTE resources (34746-8)
- Composition.ndjson includes ADMISSION_NURSING_ASSESSMENT resources (78390-2)
- Each resource parses as valid JSON per line with correct resourceType field
- Required structural fields present in sampled resources
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from tests.integration._sr_helpers import find_ndjson, load_ndjson, run_generate

_LOINC_NURSING_SHIFT_NOTE = "34746-8"
_LOINC_ADMISSION_NURSING_ASSESSMENT = "78390-2"


@pytest.mark.integration
def test_subprocess_care_team_ndjson_wellformed() -> None:
    """Full pipeline via subprocess: CareTeam.ndjson is valid, non-empty, error-free."""
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "out"
        result = subprocess.run(
            [
                sys.executable, "-m", "clinosim.simulator.cli", "generate",
                "--country", "US",
                "--population", "100",
                "--seed", "42",
                "--format", "fhir-r4",
                "--output", str(out),
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, (
            f"generate failed (returncode={result.returncode}):\n{result.stderr}"
        )
        # PR-90 regression class: attribute/key errors appear in stderr
        for err_class in ("AttributeError", "KeyError", "TypeError"):
            assert err_class not in result.stderr, (
                f"{err_class} found in stderr — CareTeam builder may be crashing on "
                f"dict-form CIF (PR-90 class silent-no-op):\n{result.stderr[:500]}"
            )
        # CareTeam must exist and be non-empty
        f = find_ndjson(out, "CareTeam.ndjson")
        assert f.exists(), "CareTeam.ndjson missing from subprocess output"
        assert f.stat().st_size > 0, "CareTeam.ndjson empty after subprocess run"
        # Validate JSON: each non-empty line must parse and have correct resourceType
        for line in f.read_text().splitlines():
            if line.strip():
                parsed = json.loads(line)
                assert parsed.get("resourceType") == "CareTeam", (
                    f"Expected resourceType='CareTeam', got {parsed.get('resourceType')!r}"
                )


@pytest.mark.integration
def test_subprocess_nursing_shift_note_in_document_reference() -> None:
    """Subprocess run: DocumentReference.ndjson must contain NURSING_SHIFT_NOTE (34746-8)."""
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "out"
        run_generate("US", 100, 42, out)
        drefs = load_ndjson(find_ndjson(out, "DocumentReference.ndjson"))
        assert drefs, "DocumentReference.ndjson empty from subprocess run"
        nursing_shift = [
            d for d in drefs
            if any(c.get("code") == _LOINC_NURSING_SHIFT_NOTE
                   for c in d.get("type", {}).get("coding", []))
        ]
        assert nursing_shift, (
            f"No NURSING_SHIFT_NOTE (LOINC {_LOINC_NURSING_SHIFT_NOTE}) in "
            "DocumentReference.ndjson from subprocess run. "
            "Nursing enricher may not be firing in the production dict CIF path."
        )


@pytest.mark.integration
def test_subprocess_nursing_composition_types_present() -> None:
    """Subprocess run: Composition.ndjson must contain ADMISSION_NURSING_ASSESSMENT (78390-2)."""
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "out"
        run_generate("US", 100, 42, out)
        comps = load_ndjson(find_ndjson(out, "Composition.ndjson"))
        assert comps, "Composition.ndjson empty from subprocess run"
        found_loinc = {
            c.get("code")
            for comp in comps
            for c in comp.get("type", {}).get("coding", [])
        }
        assert _LOINC_ADMISSION_NURSING_ASSESSMENT in found_loinc, (
            f"ADMISSION_NURSING_ASSESSMENT (LOINC {_LOINC_ADMISSION_NURSING_ASSESSMENT}) "
            "missing from Composition.ndjson in subprocess run. "
            "Nursing enricher may not be writing to CIF in the production path."
        )


@pytest.mark.integration
def test_subprocess_care_team_has_required_fields() -> None:
    """Each CareTeam from the subprocess run has required FHIR R4 fields."""
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "out"
        run_generate("US", 100, 42, out)
        care_teams = load_ndjson(find_ndjson(out, "CareTeam.ndjson"))
        if not care_teams:
            pytest.skip("No CareTeam resources emitted for n=100 cohort")
        for ct in care_teams:
            ct_id = ct.get("id", "?")
            assert ct.get("status"), f"CareTeam/{ct_id} missing status"
            assert ct.get("subject"), f"CareTeam/{ct_id} missing subject"
            assert ct.get("encounter"), f"CareTeam/{ct_id} missing encounter"
