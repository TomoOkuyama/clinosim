"""Unit tests for clinosim.audit.types — Severity, AuditFinding, AxisResult,
AuditResult, Cohort lazy NDJSON reader."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from clinosim.audit.types import (
    AuditFinding,
    AuditResult,
    AxisResult,
    Cohort,
    Severity,
)


@pytest.mark.unit
def test_severity_enum_values():
    assert Severity.INFO.value == "INFO"
    assert Severity.WARN.value == "WARN"
    assert Severity.FAIL.value == "FAIL"


@pytest.mark.unit
def test_axis_result_status_na_when_empty():
    r = AxisResult(axis="structural", module="hai")
    assert r.status == "N/A"


@pytest.mark.unit
def test_axis_result_status_pass_when_info_only():
    r = AxisResult(axis="structural", module="hai", info={"n": 100})
    assert r.status == "PASS"


@pytest.mark.unit
def test_axis_result_status_warn():
    r = AxisResult(
        axis="silent_no_op", module="hai",
        findings=[AuditFinding(Severity.WARN, "rare-event cohort")],
    )
    assert r.status == "WARN"


@pytest.mark.unit
def test_axis_result_status_fail_dominates():
    r = AxisResult(
        axis="silent_no_op", module="hai",
        findings=[
            AuditFinding(Severity.WARN, "rare"),
            AuditFinding(Severity.FAIL, "constants drift"),
        ],
    )
    assert r.status == "FAIL"


@pytest.mark.unit
def test_audit_result_overall_status():
    res = AuditResult(cohort_dir=Path("/tmp/x"), modules=["hai"], axes=["a", "b"])
    res.add("a", "hai", AxisResult(axis="a", module="hai", info={"n": 1}))
    res.add(
        "b", "hai",
        AxisResult(
            axis="b", module="hai",
            findings=[AuditFinding(Severity.FAIL, "x")],
        ),
    )
    assert res.overall_status() == "FAIL"


@pytest.mark.unit
def test_cohort_countries_and_ndjson(tmp_path: Path):
    us = tmp_path / "us" / "fhir_r4"
    us.mkdir(parents=True)
    (us / "Patient.ndjson").write_text(
        json.dumps({"resourceType": "Patient", "id": "p1"}) + "\n"
    )
    jp = tmp_path / "jp" / "fhir_r4"
    jp.mkdir(parents=True)
    (jp / "Patient.ndjson").write_text(
        json.dumps({"resourceType": "Patient", "id": "p2"}) + "\n"
    )

    coh = Cohort.open(tmp_path)
    assert coh.countries() == ["jp", "us"]

    rows = list(coh.ndjson("us", "Patient"))
    assert rows == [{"resourceType": "Patient", "id": "p1"}]


@pytest.mark.unit
def test_cohort_ndjson_missing_resource_returns_empty(tmp_path: Path):
    (tmp_path / "us" / "fhir_r4").mkdir(parents=True)
    coh = Cohort.open(tmp_path)
    assert list(coh.ndjson("us", "Observation")) == []
