"""Only valid diagnosis and report codes are emitted (Issue #3028)."""

from __future__ import annotations

import re

import pytest
import yaml

from clinosim.codes.icd10 import icd10_display, icd10_system
from clinosim.locale.loader import map_diagnosis_code
from clinosim.modules.disease.protocol import load_all_disease_protocols
from clinosim.modules.output.fhir_r4.conditions.conditions import _build_conditions

pytestmark = pytest.mark.unit

_ICD = re.compile(r"^[A-Z][0-9]{2}(\.[0-9A-Z]{1,4})?$")


def _record(working: list[dict]) -> dict:
    return {
        "patient": {"patient_id": "P1", "sex": "F", "chronic_conditions": []},
        "encounters": [{"encounter_id": "E1", "admission_datetime": "2026-01-01T10:00:00"}],
        "clinical_diagnosis": {"primary_diagnosis_code": "J18.9", "working_diagnoses": working},
    }


def _codes(country: str, working: list[dict]) -> list[str]:
    return [c["code"]["coding"][0]["code"] for c in _build_conditions(_record(working), "P1", country)]


@pytest.mark.parametrize(("country", "expected"), [("JP", "I50.9"), ("US", "I50.9")])
def test_an_in_hospital_new_disease_is_coded_by_its_icd_code(country: str, expected: str) -> None:
    codes = _codes(country, [{"disease_id": "heart_failure_exacerbation", "onset_day": 2}])
    assert expected in codes
    assert all(_ICD.match(c) for c in codes), codes


@pytest.mark.parametrize(
    ("country", "code", "emitted", "display"),
    [
        (
            "US",
            "O60.1",
            "O60.10X0",
            "Preterm labor with preterm delivery, unspecified trimester, not applicable or unspecified",
        ),
        ("US", "O24.9", "O24.919", "Unspecified diabetes mellitus in pregnancy, unspecified trimester"),
        ("JP", "O60.1", "O60.1", "早産"),
        ("JP", "O42.9", "O42.9", "前期破水，詳細不明"),
    ],
)
def test_pregnancy_complications_have_a_valid_coded_display(
    country: str, code: str, emitted: str, display: str
) -> None:
    mapped = map_diagnosis_code(code, country)
    assert mapped == emitted
    assert icd10_display(mapped, country, "ja" if country == "JP" else "en") == display


@pytest.mark.parametrize("country", ["US", "JP"])
def test_every_protocol_and_complication_code_is_a_registered_icd_code(country: str) -> None:
    codes = {p.icd_codes.get("primary", "") for p in load_all_disease_protocols().values()} - {""}
    perinatal = yaml.safe_load(open("clinosim/locale/shared/perinatal.yaml"))
    codes |= {d["code"] for d in perinatal["complications"]["bernoulli_draws"]}
    missing = []
    for code in sorted(codes):
        mapped = map_diagnosis_code(code, country)
        if not _ICD.match(mapped) or not icd10_display(mapped, country, "en"):
            missing.append((code, mapped))
    assert missing == [], f"{icd10_system(country)}: {missing}"


@pytest.mark.parametrize(("country", "text"), [("us", "Radiology Report"), ("JP", "画像診断報告書")])
def test_a_radiology_report_without_a_procedure_code_emits_no_empty_loinc(country: str, text: str) -> None:
    """A study with no modality / body site has no LOINC procedure code; the
    report's code carries no ``{"code": ""}`` coding and keeps a text."""
    from clinosim.modules.output.fhir_r4.labs.diagnostic_report import RADIOLOGY_DR_ID_PREFIX, _bb_diagnostic_reports
    from tests.unit.output.test_fhir_radiology_dr import _make_ctx, _sample_study

    study = _sample_study()
    study.modality_code = ""
    study.body_site_snomed = ""
    study.series = []
    reports = [
        r
        for r in _bb_diagnostic_reports(_make_ctx([study], country=country))
        if r["id"].startswith(RADIOLOGY_DR_ID_PREFIX)
    ]
    assert len(reports) == 1
    code = reports[0]["code"]
    assert all(c.get("code") for c in code.get("coding", [])), code
    assert code["text"] == text
