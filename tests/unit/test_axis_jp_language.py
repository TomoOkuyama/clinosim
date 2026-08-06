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


def _write_medication_admin(path, country, dosage_text, id_):
    """Helper to write MedicationAdministration resource."""
    from pathlib import Path

    p = Path(path) / country / "fhir_r4" / "MedicationAdministration.ndjson"
    p.parent.mkdir(parents=True, exist_ok=True)
    rec = {
        "resourceType": "MedicationAdministration",
        "id": id_,
        "dosage": {"text": dosage_text},
    }
    with p.open("a") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def _write_medication_request(path, country, dosage_text, id_):
    """Helper to write MedicationRequest resource."""
    from pathlib import Path

    p = Path(path) / country / "fhir_r4" / "MedicationRequest.ndjson"
    p.parent.mkdir(parents=True, exist_ok=True)
    rec = {
        "resourceType": "MedicationRequest",
        "id": id_,
        "dosageInstruction": [{"text": dosage_text}],
    }
    with p.open("a") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def _write_procedure(path, country, code_text, id_):
    """Helper to write Procedure resource."""
    from pathlib import Path

    p = Path(path) / country / "fhir_r4" / "Procedure.ndjson"
    p.parent.mkdir(parents=True, exist_ok=True)
    rec = {
        "resourceType": "Procedure",
        "id": id_,
        "code": {"text": code_text},
    }
    with p.open("a") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


@pytest.mark.unit
def test_jp_fail_medication_admin_english_dosage(tmp_path: Path, spec):
    """Issue #473: MedicationAdministration.dosage.text should be localized."""
    _write_medication_admin(tmp_path, "jp", "5.0mg DAILY", "ma-jp-1")
    result = jp_language.run(spec, Cohort.open(tmp_path))
    assert result.status == "FAIL"
    assert any("MedicationAdministration" in f.message for f in result.findings)


@pytest.mark.unit
def test_jp_pass_medication_admin_localized_dosage(tmp_path: Path, spec):
    """JP output with Japanese dosage should pass."""
    _write_medication_admin(tmp_path, "jp", "5.0mg 1日1回", "ma-jp-1")
    result = jp_language.run(spec, Cohort.open(tmp_path))
    assert result.status == "PASS"


@pytest.mark.unit
def test_jp_pass_medication_admin_units_only(tmp_path: Path, spec):
    """Units (mg, mL) are allowed in English even in JP output."""
    _write_medication_admin(tmp_path, "jp", "5.0 mg", "ma-jp-1")
    result = jp_language.run(spec, Cohort.open(tmp_path))
    assert result.status == "PASS"


@pytest.mark.unit
def test_jp_fail_medication_request_english_dosage(tmp_path: Path, spec):
    """MedicationRequest.dosageInstruction[].text should be localized."""
    _write_medication_request(tmp_path, "jp", "Take 5mg orally twice daily", "mr-jp-1")
    result = jp_language.run(spec, Cohort.open(tmp_path))
    assert result.status == "FAIL"
    assert any("MedicationRequest" in f.message for f in result.findings)


@pytest.mark.unit
def test_jp_fail_procedure_english_code_text(tmp_path: Path, spec):
    """Procedure.code.text should be localized in JP."""
    _write_procedure(tmp_path, "jp", "Chest X-ray performed", "proc-jp-1")
    result = jp_language.run(spec, Cohort.open(tmp_path))
    assert result.status == "FAIL"
    assert any("Procedure" in f.message for f in result.findings)


@pytest.mark.unit
def test_us_fail_medication_admin_japanese_dosage(tmp_path: Path, spec):
    """US output should not contain Japanese in dosage.text."""
    _write_medication_admin(tmp_path, "us", "5.0mg 1日1回", "ma-us-1")
    result = jp_language.run(spec, Cohort.open(tmp_path))
    assert result.status == "FAIL"
    assert any("US" in f.message or "non-ASCII" in f.message for f in result.findings)
