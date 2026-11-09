"""Issue #3008: a JP vaccination visit's reason is the WHO ICD-10 code of the
vaccine given (Z23 bacterial, Z24 / Z25 viral, Z26 other, Z27 combinations);
a US visit keeps the ICD-10-CM Z23."""

from __future__ import annotations

from datetime import datetime

import pytest

from clinosim.codes import lookup
from clinosim.modules.immunization.visits import vaccination_visit_reason_codes
from clinosim.modules.output.fhir_r4.encounters.encounter import _build_encounter

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("cvx", "code"),
    [
        ("150", "Z25.1"),  # influenza
        ("309", "Z25.8"),  # COVID-19
        ("04", "Z27.8"),  # MR
        ("129", "Z24.1"),  # Japanese encephalitis
        ("119", "Z25.8"),  # rotavirus
        ("19", "Z23.2"),  # BCG
        ("106", "Z27.3"),  # DTaP-IPV
        ("08", "Z24.6"),  # hepatitis B
    ],
)
def test_a_jp_vaccination_visit_is_coded_by_its_vaccine(cvx: str, code: str) -> None:
    assert vaccination_visit_reason_codes("JP", [cvx]) == [code]


def test_a_jp_influenza_visit_is_z25_1() -> None:
    assert vaccination_visit_reason_codes("JP", ["150"]) == ["Z25.1"]


def test_a_us_influenza_visit_stays_z23() -> None:
    assert vaccination_visit_reason_codes("US", ["150"]) == ["Z23"]


def test_several_vaccines_give_each_code_once_and_no_vaccine_gives_the_unspecified_code() -> None:
    assert vaccination_visit_reason_codes("JP", ["17", "133", "106", "08"]) == ["Z23.8", "Z27.3", "Z24.6"]
    assert vaccination_visit_reason_codes("JP", []) == ["Z26.9"]


def test_every_jp_schedule_vaccine_has_a_who_reason_code_with_a_japanese_title() -> None:
    from clinosim.modules.immunization.engine import load_schedule

    for name, vaccine in load_schedule("JP").items():
        for cvx in {str(vaccine["cvx"])} | {str(p["cvx"]) for p in vaccine.get("products") or []}:
            (code,) = vaccination_visit_reason_codes("JP", [cvx])
            assert code != "Z26.9", (name, cvx)
            title = lookup("icd-10", code, "ja")
            assert title and "予防接種" in title and title.endswith("の必要性"), (name, cvx, code, title)


def test_the_jp_encounter_reason_carries_the_vaccine_code() -> None:
    enc = {
        "encounter_id": "ENC-1",
        "encounter_type": "outpatient",
        "status": "completed",
        "admission_datetime": datetime(2026, 11, 1, 10).isoformat(),
        "discharge_datetime": datetime(2026, 11, 1, 10, 30).isoformat(),
        "admission_diagnosis_code": "Z23",
        "chief_complaint": "Vaccination",
    }
    resource = _build_encounter(
        enc, "P1", country="JP", admit_dx_code="Z23", admit_dx_system="icd-10", visit_reason_codes=["Z25.1"]
    )
    (reason,) = resource["reasonCode"]
    assert reason["coding"][0]["code"] == "Z25.1"
    assert reason["text"] == "インフルエンザに対する予防接種の必要性"


@pytest.mark.parametrize(("country", "codes"), [("JP", ["Z24.1"]), ("US", ["Z23"])])
def test_a_procedure_of_a_vaccination_visit_names_the_visit_reason(country: str, codes: list[str]) -> None:
    from clinosim.modules.output.fhir_r4.procedures.procedures import _build_procedure

    proc = {
        "procedure_id": "PROC-1",
        "encounter_id": "ENC-1",
        "procedure_type": "vital_signs_measurement",
        "start_datetime": "2026-06-01T10:00:00",
        "end_datetime": "2026-06-01T10:05:00",
    }
    record = {
        "clinical_diagnosis": {"admission_diagnosis_code": "Z23"},
        "immunizations": [{"vaccine_cvx": "129", "encounter_id": "ENC-1"}],
    }
    resource = _build_procedure(proc, "P1", 0, country, record=record)
    assert [rc["coding"][0]["code"] for rc in resource["reasonCode"]] == codes
