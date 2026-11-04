"""One NDJSON reader for audit and eval (Issue #2518)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from clinosim.audit.types import Cohort


def _cohort(tmp_path: Path) -> Cohort:
    base = tmp_path / "US" / "fhir_r4"
    base.mkdir(parents=True)
    (base / "Patient.ndjson").write_text(json.dumps({"id": "a"}) + "\n\n{broken\n" + json.dumps({"id": "b"}) + "\n")
    (base / "Encounter.ndjson").write_text(json.dumps({"id": "e"}) + "\n")
    return Cohort.open(tmp_path)


def test_malformed_lines_raise_by_default(tmp_path: Path) -> None:
    with pytest.raises(json.JSONDecodeError):
        list(_cohort(tmp_path).ndjson("US", "Patient"))


def test_malformed_lines_are_skipped_when_asked(tmp_path: Path) -> None:
    rows = list(_cohort(tmp_path).ndjson("US", "Patient", skip_malformed=True))
    assert [r["id"] for r in rows] == ["a", "b"]


def test_missing_resource_file_yields_nothing(tmp_path: Path) -> None:
    assert list(_cohort(tmp_path).ndjson("US", "Observation")) == []


def test_resource_files_are_sorted(tmp_path: Path) -> None:
    cohort = _cohort(tmp_path)
    assert [p.name for p in cohort.resource_files("US")] == ["Encounter.ndjson", "Patient.ndjson"]
    assert cohort.resource_files("JP") == []
