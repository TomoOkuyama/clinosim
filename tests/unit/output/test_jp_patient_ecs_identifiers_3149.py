"""The JP Patient carries the JP-CLINS eCS identifiers (Issue #3149):
R1010 facility patient-ID system and R1012/R1013 insured-person identifier."""

from __future__ import annotations

import copy
import re
from types import SimpleNamespace

import pytest

from clinosim.locale.loaders.fhir_identity import load_facility_identity
from clinosim.modules.output.fhir_r4.demographics.patient import _build_coverage_resources
from clinosim.modules.output.fhir_r4.lib.inline_bb import _bb_patient

pytestmark = pytest.mark.unit

_INSURED = "http://jpfhir.jp/fhir/clins/Idsystem/JP_Insurance_memberID"
_PUBLIC = "http://jpfhir.jp/fhir/clins/Idsystem/JP_PublicPayer_memberID"
_OID = "urn:oid:1.2.392.100495.20.3.51."
# The JP_Patient_eCS FHIRPath rules, as regular expressions.
_R1010 = re.compile(r"^[0-4][0-9][1-3][0-9]{7}$")
_R1013 = re.compile(r"^[0-9]{8}:[^:\s　]*:[^:\s　]*:(|[0-9][0-9])$")

_PATIENT = {
    "patient_id": "POP-003149",
    "sex": "F",
    "date_of_birth": "1960-05-01",
    "name": {"family_name": "山田", "given_name": "花子"},
    "address": {"state": "東京都", "city": "世田谷区"},
    "identity": {
        "enrollments": [
            {
                "country": "JP",
                "category": "national",
                "insurer_number": "130120",
                "member_id": "4567",
                "group_symbol": "世田",
                "branch_number": None,
            }
        ]
    },
}
_ENCS = [{"encounter_id": "E1", "admission_datetime": "2024-06-01T09:00:00"}]


def _patient(data: dict, country: str = "JP") -> dict:
    ctx = SimpleNamespace(patient_data=data, country=country, record={"encounters": _ENCS}, snapshot_date="2024-12-31")
    return _bb_patient(ctx)[0]


def test_facility_patient_id_system_is_built_from_the_institution_code() -> None:
    mrn = [i for i in _patient(_PATIENT)["identifier"] if str(i.get("system", "")).startswith(_OID)]
    assert len(mrn) == 1
    system = mrn[0]["system"]
    code = load_facility_identity("JP")["institution_code"]
    assert system == f"{_OID}1{code}"
    assert system[31] == "1" and _R1010.match(system[32:])


def test_us_patient_keeps_its_mrn_system_and_has_no_insured_identifier() -> None:
    systems = [i.get("system") for i in _patient(_PATIENT, "US")["identifier"]]
    assert "https://clinosim.io/fhir/us/mrn" in systems
    assert _INSURED not in systems


def test_jp_patient_has_exactly_one_insured_person_identifier() -> None:
    insured = [i for i in _patient(_PATIENT)["identifier"] if i.get("system") in (_INSURED, _PUBLIC)]
    assert len(insured) == 1
    # A 6-digit 国民健康保険 insurer number is zero-padded to 8 digits; no 枝番 → empty.
    assert insured[0]["value"] == "00130120:世田:4567:"
    assert _R1013.match(insured[0]["value"])


def test_the_insured_identifier_is_the_current_coverage() -> None:
    data = copy.deepcopy(_PATIENT)
    data["date_of_birth"] = "1949-06-15"  # turns 75 in 2024: 後期高齢者医療 from the birthday
    insured = [i for i in _patient(data)["identifier"] if i.get("system") == _INSURED]
    assert len(insured) == 1
    assert insured[0]["value"].startswith("39130000::")
    assert _R1013.match(insured[0]["value"])


@pytest.mark.parametrize(
    ("enrollment", "expected"),
    [
        (
            {
                "category": "national",
                "insurer_number": "130120",
                "member_id": "9",
                "group_symbol": None,
                "branch_number": None,
            },
            "00130120::9:",
        ),
        (
            {
                "category": "employee",
                "insurer_number": "01130012",
                "member_id": "12",
                "group_symbol": "34",
                "branch_number": "01",
            },
            "01130012:34:12:01",
        ),
    ],
)
def test_coverage_member_identifier_follows_the_insured_person_format(enrollment: dict, expected: str) -> None:
    data = copy.deepcopy(_PATIENT)
    data["identity"]["enrollments"] = [{"country": "JP", **enrollment}]
    cov = next(r for r in _build_coverage_resources(data, "JP", _ENCS, "2024-12-31") if r["resourceType"] == "Coverage")
    assert cov["identifier"][0] == {"system": _INSURED, "value": expected}
