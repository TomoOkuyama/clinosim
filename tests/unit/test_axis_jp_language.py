"""Unit tests for clinosim.audit.axes.jp_language."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from clinosim.audit.axes import jp_language
from clinosim.audit.registry import ModuleAuditSpec
from clinosim.audit.types import Cohort


def _write_obs(path: Path, country: str, code: str, display: str, id_: str):
    p = path / country / "fhir_r4" / "Observation.ndjson"
    p.parent.mkdir(parents=True, exist_ok=True)
    rec = {
        "resourceType": "Observation",
        "id": id_,
        "code": {"coding": [{"code": code, "display": display}]},
    }
    with p.open("a") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


@pytest.fixture
def spec():
    return ModuleAuditSpec(
        name="hai",
        structural_obs_codes={"WBC": ("6690-2", "2A010"), "CRP": ("1988-5", "5C070")},
    )


@pytest.mark.unit
def test_jp_pass_with_localized_displays(tmp_path: Path, spec):
    _write_obs(tmp_path, "us", "6690-2", "Leukocytes", "us-wbc-1")
    _write_obs(tmp_path, "jp", "2A010", "白血球数", "jp-wbc-1")
    _write_obs(tmp_path, "jp", "5C070", "C反応性蛋白", "jp-crp-1")
    result = jp_language.run(spec, Cohort.open(tmp_path))
    assert result.status == "PASS"


@pytest.mark.unit
def test_jp_fail_when_us_has_non_ascii(tmp_path: Path, spec):
    _write_obs(tmp_path, "us", "6690-2", "白血球数", "us-wbc-1")
    result = jp_language.run(spec, Cohort.open(tmp_path))
    assert result.status == "FAIL"
    assert any("non-ASCII" in f.message or "US" in f.message for f in result.findings)


@pytest.mark.unit
def test_jp_fail_when_jp_display_not_localized(tmp_path: Path, spec):
    _write_obs(tmp_path, "jp", "2A010", "Leukocytes", "jp-wbc-1")  # ASCII only
    result = jp_language.run(spec, Cohort.open(tmp_path))
    assert result.status == "FAIL"
    assert any("WBC" in f.message for f in result.findings)


@pytest.mark.unit
def test_jp_na_when_no_jp_country(tmp_path: Path, spec):
    _write_obs(tmp_path, "us", "6690-2", "Leukocytes", "us-wbc-1")
    result = jp_language.run(spec, Cohort.open(tmp_path))
    # US scan ran (info populated, 0 violations) → PASS
    assert result.status == "PASS"
