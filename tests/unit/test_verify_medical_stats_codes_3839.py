"""verify_medical_stats counts the codes of the cohort's own code system
(Issue #3839): a JP cohort carries WHO ICD-10 F17.2 / F10.2, a US cohort the
ICD-10-CM leaves."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "verify_medical_stats.py"


def _bundle(tmp_path: Path, codes: list[str]) -> Path:
    fhir = tmp_path / "fhir_r4"
    fhir.mkdir()
    rows = []
    conds = []
    for i, code in enumerate(codes):
        rows.append({"resourceType": "Patient", "id": f"p{i}", "gender": "male", "birthDate": "1970-01-01"})
        conds.append(
            {
                "resourceType": "Condition",
                "id": f"c{i}",
                "subject": {"reference": f"Patient/p{i}"},
                "code": {"coding": [{"code": code}]},
            }
        )
    (fhir / "Patient.ndjson").write_text("\n".join(json.dumps(r) for r in rows))
    (fhir / "Condition.ndjson").write_text("\n".join(json.dumps(c) for c in conds))
    return tmp_path


def _counts(tmp_path: Path, country: str, codes: list[str]) -> dict[str, int]:
    out = subprocess.run(
        [sys.executable, str(SCRIPT), str(_bundle(tmp_path, codes)), country],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    result = {}
    for key in ("tobacco_use_prev", "alcohol_use_disorder_prev"):
        line = next(ln for ln in out.splitlines() if key in ln)
        result[key] = int(re.search(r"n=(\d+)", line).group(1))
    return result


def test_jp_prefixes_count_f17_2_and_f10_2(tmp_path: Path) -> None:
    counts = _counts(tmp_path, "JP", ["F17.2", "F17.2", "F10.2", "I10"])
    assert counts == {"tobacco_use_prev": 2, "alcohol_use_disorder_prev": 1}


def test_us_prefixes_are_unchanged(tmp_path: Path) -> None:
    counts = _counts(tmp_path, "US", ["F17.210", "F10.20", "F10.21", "F17.2", "I10"])
    # the WHO codes are not US codes: only the ICD-10-CM leaves count
    assert counts == {"tobacco_use_prev": 1, "alcohol_use_disorder_prev": 2}
