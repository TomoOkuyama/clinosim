"""Unit tests for clinosim.audit.axes.clinical (Phase 1 cohort baseline +
acceptance subset)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from clinosim.audit.axes import clinical
from clinosim.audit.registry import ModuleAuditSpec
from clinosim.audit.types import Cohort
from clinosim.modules.output._fhir_microbiology import MB_ORG_ID_PREFIX, MB_SUS_ID_PREFIX


def _write(path: Path, country: str, file: str, rows: list[dict]):
    p = path / country / "fhir_r4" / file
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


def _wbc(enc: str, val: float, oid: str):
    return {
        "resourceType": "Observation",
        "id": oid,
        "code": {"coding": [{"code": "6690-2"}]},
        "encounter": {"reference": f"Encounter/{enc}"},
        "valueQuantity": {"value": val},
    }


def _crp(enc: str, val: float, oid: str):
    return {
        "resourceType": "Observation",
        "id": oid,
        "code": {"coding": [{"code": "1988-5"}]},
        "encounter": {"reference": f"Encounter/{enc}"},
        "valueQuantity": {"value": val},
    }


def _cauti_cond(enc: str, cid: str):
    return {
        "resourceType": "Condition",
        "id": cid,
        "code": {"coding": [{"code": "T83.511A"}]},
        "encounter": {"reference": f"Encounter/{enc}"},
    }


def _imp_enc(eid: str):
    return {
        "resourceType": "Encounter", "id": eid,
        "class": {"code": "IMP"},
    }


@pytest.fixture
def hai_spec():
    return ModuleAuditSpec(
        name="hai",
        structural_obs_codes={"WBC": ("6690-2",), "CRP": ("1988-5",)},
        clinical_acceptance={
            "cauti": {
                "icd10_code": "T83.511A",
                "WBC_delta_p50": 1500,
                "CRP_delta_p50": 25,
            },
        },
    )


@pytest.mark.unit
def test_clinical_pass_when_cauti_cohort_exceeds_acceptance(
    tmp_path: Path, hai_spec,
):
    # 5 cohort obs (n>=5 to bypass WARN) + baseline
    _write(tmp_path, "us", "Encounter.ndjson", [
        _imp_enc(f"E-CAUTI-{i}") for i in range(5)
    ] + [
        _imp_enc(f"E-BASE-{i}") for i in range(5)
    ])
    _write(tmp_path, "us", "Condition.ndjson", [
        _cauti_cond(f"E-CAUTI-{i}", f"c-{i}") for i in range(5)
    ])
    _write(tmp_path, "us", "Observation.ndjson", [
        _wbc(f"E-CAUTI-{i}", 14000, f"o-c-w-{i}") for i in range(5)
    ] + [
        _crp(f"E-CAUTI-{i}", 75, f"o-c-c-{i}") for i in range(5)
    ] + [
        _wbc(f"E-BASE-{i}", 12000, f"o-b-w-{i}") for i in range(5)
    ] + [
        _crp(f"E-BASE-{i}", 25, f"o-b-c-{i}") for i in range(5)
    ])
    result = clinical.run(hai_spec, Cohort.open(tmp_path))
    assert result.status == "PASS"


@pytest.mark.unit
def test_clinical_fail_when_cohort_misses_acceptance(tmp_path: Path, hai_spec):
    _write(tmp_path, "us", "Encounter.ndjson", [
        _imp_enc(f"E-CAUTI-{i}") for i in range(5)
    ] + [
        _imp_enc(f"E-BASE-{i}") for i in range(5)
    ])
    _write(tmp_path, "us", "Condition.ndjson", [
        _cauti_cond(f"E-CAUTI-{i}", f"c-{i}") for i in range(5)
    ])
    _write(tmp_path, "us", "Observation.ndjson", [
        _wbc(f"E-CAUTI-{i}", 12100, f"o-c-w-{i}") for i in range(5)  # delta +100
    ] + [
        _wbc(f"E-BASE-{i}", 12000, f"o-b-w-{i}") for i in range(5)
    ])
    result = clinical.run(hai_spec, Cohort.open(tmp_path))
    assert result.status == "FAIL"


@pytest.mark.unit
def test_clinical_warn_when_cohort_rare(tmp_path: Path, hai_spec):
    # No CAUTI Condition → cohort_n = 0 → rare-event WARN, not FAIL
    _write(tmp_path, "us", "Encounter.ndjson", [_imp_enc("E-1")])
    _write(tmp_path, "us", "Observation.ndjson",
           [_wbc("E-1", 12000, "o-1")])
    result = clinical.run(hai_spec, Cohort.open(tmp_path))
    assert result.status == "WARN"


@pytest.mark.unit
def test_clinical_na_when_spec_has_no_acceptance(tmp_path: Path):
    spec = ModuleAuditSpec(
        name="hai",
        structural_obs_codes={"WBC": ("6690-2",), "CRP": ("1988-5",)},
    )
    result = clinical.run(spec, Cohort.open(tmp_path))
    assert result.status == "N/A"


@pytest.mark.unit
def test_check_lab_obs_basedon_excludes_microbiology(tmp_path: Path):
    """Microbiology Observations (mb-org-*, mb-sus-*) MUST NOT be counted
    by the basedOn coverage gate even though they carry 'laboratory' category.

    Rationale: PR1 scope = lab panel orders only.  Microbiology SR support
    is Tier 2 backlog.  Without this exclusion the gate would FAIL on any
    cohort with HAI events, masking genuine basedOn gaps.
    """
    lab_category = {
        "coding": [{"system": "http://terminology.hl7.org/CodeSystem/v2-0074", "code": "LAB"}]
    }

    def _mb_obs(obs_id: str) -> dict:
        return {
            "resourceType": "Observation",
            "id": obs_id,
            "category": [lab_category],
            "code": {"coding": [{"code": "some-mb-code"}]},
            # intentionally NO basedOn
        }

    # Write 1 mb-org-* + 1 mb-sus-* Observation with no basedOn, empty SR file.
    _write(tmp_path, "us", "Observation.ndjson", [
        _mb_obs(f"{MB_ORG_ID_PREFIX}enc-001-0"),
        _mb_obs(f"{MB_SUS_ID_PREFIX}enc-001-0-0"),
    ])
    _write(tmp_path, "us", "ServiceRequest.ndjson", [])

    spec = ModuleAuditSpec(
        name="order_service_request",
        structural_obs_codes={},
        clinical_acceptance={"basedon_coverage": {}},
    )
    result = clinical.run(spec, Cohort.open(tmp_path))

    # lab_obs_count should be 0 (both mb-* observations excluded) →
    # gate emits a WARN (n < 30) not a FAIL.
    assert result.status == "WARN", (
        f"Expected WARN (microbiology excluded → lab_obs_count=0 < 30), "
        f"got {result.status!r}. Findings: {result.findings}"
    )
