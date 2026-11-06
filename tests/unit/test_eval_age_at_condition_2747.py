"""Issue #2747: age-condition consistency scores the age at the condition, not today's age."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

import clinosim.eval.axes.clinical as clinical
from clinosim.audit.types import Cohort

pytestmark = pytest.mark.unit


def _cohort(tmp_path: Path, onset: str) -> Cohort:
    base = tmp_path / "US" / "fhir_r4"
    base.mkdir(parents=True)
    (base / "Patient.ndjson").write_text(
        json.dumps({"resourceType": "Patient", "id": "P1", "birthDate": "2015-03-01"}) + "\n"
    )
    cond = {
        "resourceType": "Condition",
        "id": "C1",
        "subject": {"reference": "Patient/P1"},
        "code": {"coding": [{"code": "I10"}]},
        "onsetDateTime": onset,
    }
    (base / "Condition.ndjson").write_text(json.dumps(cond) + "\n")
    return Cohort.open(tmp_path)


class _FarFuture(date):
    @classmethod
    def today(cls) -> date:
        return date(2040, 1, 1)


def test_a_child_condition_is_scored_at_the_childs_age_whatever_the_run_date(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(clinical, "date", _FarFuture)  # the run date must not matter
    check = clinical._check_age_condition_consistency(_cohort(tmp_path, "2025-06-01"), "US")
    assert check.outcome.name == "FAIL"


def test_the_same_condition_as_an_adult_passes(tmp_path: Path) -> None:
    check = clinical._check_age_condition_consistency(_cohort(tmp_path, "2034-06-01"), "US")
    assert check.outcome.name == "PASS"
