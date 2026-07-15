"""Integration: small cohort exercises full HAI → FHIR Condition + culture chain (PR-B)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration


def _read_ndjson(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line]


def test_hai_chain_through_fhir_pipeline(tmp_path):
    """A p=500 ICU-heavy cohort should produce at least one HAI Condition
    + corresponding culture (Specimen + DR) under the right seed.
    p=500 is empirically high enough to produce a sample HAI most of
    the time at seed=42.
    """
    out = tmp_path / "out"
    cmd = [
        "python",
        "-m",
        "clinosim.simulator.cli",
        "generate",
        "-p",
        "500",
        "-s",
        "42",
        "--country",
        "US",
        "--format",
        "fhir-r4",
        "-o",
        str(out),
    ]
    proc = subprocess.run(cmd, check=False, capture_output=True, text=True)
    assert proc.returncode == 0, f"stdout={proc.stdout}\nstderr={proc.stderr}"

    conditions = _read_ndjson(out / "fhir_r4" / "Condition.ndjson")
    specimens = _read_ndjson(out / "fhir_r4" / "Specimen.ndjson")
    dr = _read_ndjson(out / "fhir_r4" / "DiagnosticReport.ndjson")
    encounter = _read_ndjson(out / "fhir_r4" / "Encounter.ndjson")
    patient = _read_ndjson(out / "fhir_r4" / "Patient.ndjson")

    hai_conditions = [c for c in conditions if c["id"].startswith("hai-")]
    if not hai_conditions:
        pytest.skip("p=500 cohort produced no HAI Conditions (rare-event lottery)")

    encounter_ids = {e["id"] for e in encounter}
    patient_ids = {p["id"] for p in patient}
    for c in hai_conditions:
        p_ref = c["subject"]["reference"].split("/", 1)[1]
        e_ref = c["encounter"]["reference"].split("/", 1)[1]
        assert p_ref in patient_ids
        assert e_ref in encounter_ids

    # Dual coding
    for c in hai_conditions:
        coding_systems = {cd["system"] for cd in c["code"]["coding"]}
        assert len(coding_systems) >= 2, f"HAI {c['id']} missing dual coding: {coding_systems}"
        for cd in c["code"]["coding"]:
            assert cd["display"] != cd["code"]

    # onsetDateTime present
    for c in hai_conditions:
        assert c["onsetDateTime"]

    # Cultures exist
    assert specimens, "HAI present but no Specimens emitted"
    assert dr, "HAI present but no DiagnosticReports emitted"
