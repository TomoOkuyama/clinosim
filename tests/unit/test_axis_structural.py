"""Unit tests for clinosim.audit.axes.structural."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from clinosim.audit.axes import structural
from clinosim.audit.registry import ModuleAuditSpec
from clinosim.audit.types import Cohort


def _write_obs(path: Path, codes: list[dict], **extra):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        rec = {
            "resourceType": "Observation",
            "id": extra.pop("id", "obs-1"),
            "code": {"coding": codes},
            **extra,
        }
        f.write(json.dumps(rec) + "\n")


@pytest.fixture
def hai_spec():
    return ModuleAuditSpec(
        name="hai",
        structural_obs_codes={"WBC": ("6690-2",), "CRP": ("1988-5",)},
    )


@pytest.mark.unit
def test_structural_pass_when_full_coverage(tmp_path: Path, hai_spec):
    obs = tmp_path / "us" / "fhir_r4" / "Observation.ndjson"
    _write_obs(
        obs,
        [{"code": "6690-2", "display": "WBC"}],
        referenceRange=[{"low": {"value": 4500}}],
        interpretation=[{"text": "N"}],
    )
    _write_obs(
        obs,
        [{"code": "1988-5", "display": "CRP"}],
        referenceRange=[{"low": {"value": 0}}],
        interpretation=[{"text": "N"}],
        id="obs-2",
    )
    result = structural.run(hai_spec, Cohort.open(tmp_path))
    assert result.status == "PASS"


@pytest.mark.unit
def test_structural_fail_missing_refRange(tmp_path: Path, hai_spec):
    obs = tmp_path / "us" / "fhir_r4" / "Observation.ndjson"
    _write_obs(obs, [{"code": "6690-2", "display": "WBC"}], interpretation=[{"text": "N"}])  # no referenceRange
    result = structural.run(hai_spec, Cohort.open(tmp_path))
    assert result.status == "FAIL"
    assert any("refRange" in f.message for f in result.findings)


@pytest.mark.unit
def test_structural_fail_duplicate_id(tmp_path: Path, hai_spec):
    obs = tmp_path / "us" / "fhir_r4" / "Observation.ndjson"
    _write_obs(obs, [{"code": "6690-2", "display": "WBC"}], id="dup", referenceRange=[{}], interpretation=[{}])
    _write_obs(obs, [{"code": "1988-5", "display": "CRP"}], id="dup", referenceRange=[{}], interpretation=[{}])
    result = structural.run(hai_spec, Cohort.open(tmp_path))
    assert result.status == "FAIL"
    assert any("duplicate" in f.message.lower() for f in result.findings)


@pytest.mark.unit
def test_structural_fail_display_equals_code(tmp_path: Path, hai_spec):
    obs = tmp_path / "us" / "fhir_r4" / "Observation.ndjson"
    _write_obs(obs, [{"code": "6690-2", "display": "6690-2"}], referenceRange=[{}], interpretation=[{}])
    result = structural.run(hai_spec, Cohort.open(tmp_path))
    assert result.status == "FAIL"
    assert any("display" in f.message.lower() for f in result.findings)


@pytest.mark.unit
def test_structural_na_when_no_matching_codes(tmp_path: Path, hai_spec):
    (tmp_path / "us" / "fhir_r4").mkdir(parents=True)
    result = structural.run(hai_spec, Cohort.open(tmp_path))
    assert result.status == "N/A"
