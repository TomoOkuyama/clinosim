"""Integration: subprocess run-beta → document NDJSON full-pipeline (PR-90 教訓).

Exercises the production json.dump → json.load → dict CIF path that unit tests
with dataclass fixtures cannot cover.  PR1 ServiceRequest LAB exposed a bug
where the builder crashed on production dict CIF; this test guards the same
anti-pattern for the new document builders:
  _bb_document_references, _bb_compositions, _bb_allergy_intolerances,
  _bb_clinical_impressions.

Guards:
- No AttributeError / KeyError / TypeError in stderr (PR-90 silent-no-op class)
- DocumentReference.ndjson, Composition.ndjson, ClinicalImpression.ndjson,
  AllergyIntolerance.ndjson exist and are non-empty
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


@pytest.mark.integration
def test_subprocess_produces_well_formed_document_ndjson() -> None:
    """Full pipeline via subprocess: all document NDJSON files are valid and error-free."""
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
                f"{err_class} found in stderr — document builder may be crashing on "
                f"dict-form CIF (PR-90 class silent-no-op):\n{result.stderr[:500]}"
            )
        # All document-chain NDJSONs must exist and be non-empty
        for resource in ("DocumentReference", "Composition", "ClinicalImpression",
                         "AllergyIntolerance"):
            f = find_ndjson(out, f"{resource}.ndjson")
            assert f.exists(), f"{resource}.ndjson missing from subprocess output"
            assert f.stat().st_size > 0, f"{resource}.ndjson empty after subprocess run"
            # Validate JSON: each non-empty line must parse and have correct resourceType
            for line in f.read_text().splitlines():
                if line.strip():
                    parsed = json.loads(line)
                    assert parsed.get("resourceType") == resource, (
                        f"Expected resourceType={resource!r}, "
                        f"got {parsed.get('resourceType')!r}"
                    )


@pytest.mark.integration
def test_subprocess_document_reference_has_required_fields() -> None:
    """Each DocumentReference from the subprocess run has required FHIR R4 fields."""
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "out"
        run_generate("US", 100, 42, out)
        drefs = load_ndjson(find_ndjson(out, "DocumentReference.ndjson"))
        if not drefs:
            pytest.skip("No DocumentReference resources emitted for n=100 cohort")
        for dr in drefs:
            dr_id = dr.get("id", "?")
            assert dr.get("status") in {"current", "superseded", "entered-in-error"}, (
                f"DocumentReference/{dr_id} unexpected status {dr.get('status')!r}"
            )
            assert dr.get("type"), f"DocumentReference/{dr_id} missing type"
            assert dr.get("subject"), f"DocumentReference/{dr_id} missing subject"
            content = dr.get("content", [])
            assert content, f"DocumentReference/{dr_id} missing content[]"
            assert content[0].get("attachment"), (
                f"DocumentReference/{dr_id} content[0].attachment missing"
            )


@pytest.mark.integration
def test_subprocess_composition_has_required_fields() -> None:
    """Each Composition from the subprocess run has required FHIR R4 fields."""
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "out"
        run_generate("US", 100, 42, out)
        comps = load_ndjson(find_ndjson(out, "Composition.ndjson"))
        if not comps:
            pytest.skip("No Composition resources emitted for n=100 cohort")
        for comp in comps:
            comp_id = comp.get("id", "?")
            assert comp.get("status") == "final", (
                f"Composition/{comp_id} expected status='final', got {comp.get('status')!r}"
            )
            assert comp.get("type"), f"Composition/{comp_id} missing type"
            assert comp.get("subject"), f"Composition/{comp_id} missing subject"
            assert comp.get("date"), f"Composition/{comp_id} missing date"
            assert comp.get("title"), f"Composition/{comp_id} missing title"


@pytest.mark.integration
def test_subprocess_clinical_impression_has_required_fields() -> None:
    """Each ClinicalImpression from the subprocess run has required FHIR R4 fields."""
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "out"
        run_generate("US", 100, 42, out)
        impressions = load_ndjson(find_ndjson(out, "ClinicalImpression.ndjson"))
        if not impressions:
            pytest.skip("No ClinicalImpression resources emitted for n=100 cohort")
        for ci in impressions:
            ci_id = ci.get("id", "?")
            # FHIR R4 ClinicalImpression.status is `in-progress | completed |
            # entered-in-error`. In-progress encounters at the snapshot date (AD-32)
            # legitimately yield in-progress impressions, so accept both valid
            # generated statuses rather than requiring "completed" (cohort composition
            # is seed-dependent — an in-progress encounter may or may not appear).
            assert ci.get("status") in ("completed", "in-progress"), (
                f"ClinicalImpression/{ci_id} unexpected status {ci.get('status')!r}"
            )
            assert ci.get("subject"), f"ClinicalImpression/{ci_id} missing subject"
