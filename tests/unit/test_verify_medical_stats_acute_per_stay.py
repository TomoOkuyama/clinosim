"""verify_medical_stats counts an acute event once per stay: a sepsis stay
carries its admission code (A41.9), the organism-specific discharge code
(A41.51) and the severity code (R65.20) as separate Conditions, and counting
Conditions put the sepsis incidence at about 2.4 events per stay."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "verify_medical_stats.py"


def _cases(tmp_path: Path, conditions: list[tuple[str, str, str | None]]) -> int:
    fhir = tmp_path / "fhir_r4"
    fhir.mkdir()
    pids = sorted({p for p, _, _ in conditions})
    (fhir / "Patient.ndjson").write_text(
        "\n".join(
            json.dumps({"resourceType": "Patient", "id": p, "gender": "male", "birthDate": "1970-01-01"}) for p in pids
        )
    )
    rows = []
    for i, (pid, code, enc) in enumerate(conditions):
        row = {
            "resourceType": "Condition",
            "id": f"c{i}",
            "subject": {"reference": f"Patient/{pid}"},
            "code": {"coding": [{"code": code}]},
        }
        if enc:
            row["encounter"] = {"reference": f"Encounter/{enc}"}
        rows.append(row)
    (fhir / "Condition.ndjson").write_text("\n".join(json.dumps(r) for r in rows))
    out = subprocess.run(
        [sys.executable, str(SCRIPT), str(tmp_path), "US"], capture_output=True, text=True, check=True
    ).stdout
    line = next(ln for ln in out.splitlines() if "sepsis_incidence" in ln)
    return int(re.search(r"cases n=(\d+)", line).group(1))


def test_one_sepsis_stay_with_three_codes_is_one_case(tmp_path: Path) -> None:
    assert _cases(tmp_path, [("p1", "A41.9", "e1"), ("p1", "A41.51", "e1"), ("p1", "R65.20", "e1")]) == 1


def test_two_stays_of_one_patient_are_two_cases(tmp_path: Path) -> None:
    assert _cases(tmp_path, [("p1", "A41.9", "e1"), ("p1", "A41.9", "e2")]) == 2


def test_a_condition_without_an_encounter_counts_on_its_own(tmp_path: Path) -> None:
    assert _cases(tmp_path, [("p1", "A41.9", None), ("p2", "A41.9", None)]) == 2
