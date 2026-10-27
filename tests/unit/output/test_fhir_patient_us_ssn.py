"""US Patient.identifier carries a synthetic SSN slice (type SS, us-ssn system)."""

from __future__ import annotations

import re

import pytest

from clinosim.modules.output.fhir_r4.demographics.patient import _build_patient

pytestmark = pytest.mark.unit

_SSN_SYSTEM = "http://hl7.org/fhir/sid/us-ssn"
_SSN_PATTERN = re.compile(r"^9\d{2}-(?!00)\d{2}-(?!0000)\d{4}$")


def _patient(pid: str = "POP-000123") -> dict:
    return {
        "patient_id": pid,
        "sex": "F",
        "date_of_birth": "1970-05-01",
        "family_name": "Smith",
        "given_name": "Anna",
    }


def _ssn_identifiers(resource: dict) -> list[dict]:
    return [i for i in resource.get("identifier", []) if i.get("system") == _SSN_SYSTEM]


def test_us_patient_has_one_ssn_identifier() -> None:
    ids = _ssn_identifiers(_build_patient(_patient(), "US"))
    assert len(ids) == 1
    coding = ids[0]["type"]["coding"][0]
    assert coding["system"] == "http://terminology.hl7.org/CodeSystem/v2-0203"
    assert coding["code"] == "SS"


@pytest.mark.parametrize("pid", [f"POP-{n:06d}" for n in range(0, 2000, 37)])
def test_us_ssn_stays_in_never_issued_9xx_area(pid: str) -> None:
    value = _ssn_identifiers(_build_patient(_patient(pid), "US"))[0]["value"]
    assert _SSN_PATTERN.match(value), value


def test_us_ssn_is_deterministic_and_patient_specific() -> None:
    a1 = _ssn_identifiers(_build_patient(_patient("POP-000001"), "US"))[0]["value"]
    a2 = _ssn_identifiers(_build_patient(_patient("POP-000001"), "US"))[0]["value"]
    b = _ssn_identifiers(_build_patient(_patient("POP-000002"), "US"))[0]["value"]
    assert a1 == a2
    assert a1 != b


def test_jp_patient_has_no_ssn_identifier() -> None:
    assert _ssn_identifiers(_build_patient(_patient(), "JP")) == []
