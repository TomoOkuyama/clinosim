"""Issue #3000: a minor's Coverage is a dependant's, and starts no earlier than birth.

A child on a parent's plan (US private / employer / self-pay, JP 被扶養者) is
covered with relationship ``child``: the subscriber is the guardian when the
record names one (the mother of a child born in the simulation), otherwise the
policy holder is named by role only. A child enrolled in Medicaid / CHIP is the
enrollee (``self``). Coverage.period never starts before the birth date.
"""

from __future__ import annotations

import pytest

from clinosim.modules.output.fhir_r4.demographics.patient import _build_coverage_resources, patient_ref

pytestmark = pytest.mark.unit


def _patient(category: str, dob: str, country: str = "US", **extra: object) -> dict:
    enr = {"country": country, "category": category, "insurer_number": "US-BCBS", "member_id": "12345678901"}
    if country == "JP":
        enr.update(insurer_number="01130012", group_symbol="1234", branch_number="02")
    return {"patient_id": "POP-000180-BABY", "date_of_birth": dob, "identity": {"enrollments": [enr]}, **extra}


def _coverages(patient: dict, country: str = "US", encounters: list | None = None) -> list[dict]:
    res = _build_coverage_resources(patient, country, encounters=encounters)
    return [r for r in res if r["resourceType"] == "Coverage"]


_BIRTH_STAY = [{"admission_datetime": "2023-10-12T03:10:00", "discharge_datetime": "2023-10-14T10:00:00"}]
_MOTHER = {"contact": {"emergency_contact_name": "Jane Smith", "emergency_contact_relationship": "MTH"}}


def test_newborn_coverage_starts_at_birth_as_the_mothers_child() -> None:
    [cov] = _coverages(_patient("private", "2023-10-12", **_MOTHER), encounters=_BIRTH_STAY)
    assert cov["period"]["start"] == "2023-10-12"
    assert cov["relationship"]["coding"][0]["code"] == "child"
    assert cov["subscriber"] == {"display": "Jane Smith"}
    assert cov["beneficiary"] == patient_ref("POP-000180-BABY")


def test_minor_without_a_known_guardian_names_the_policy_holder_by_role() -> None:
    encs = [{"admission_datetime": "2025-03-01T10:00:00"}]
    [cov] = _coverages(_patient("private", "2012-05-01"), encounters=encs)
    assert cov["relationship"]["coding"][0]["code"] == "child"
    assert "subscriber" not in cov
    assert cov["policyHolder"] == {"display": "Parent or guardian"}


def test_child_on_chip_is_the_enrollee() -> None:
    encs = [{"admission_datetime": "2025-03-01T10:00:00"}]
    [cov] = _coverages(_patient("medicaid_chip", "2012-05-01"), encounters=encs)
    assert cov["relationship"]["coding"][0]["code"] == "self"
    assert cov["subscriber"] == patient_ref("POP-000180-BABY")


def test_adult_stays_the_self_subscriber() -> None:
    encs = [{"admission_datetime": "2025-03-01T10:00:00"}]
    [cov] = _coverages(_patient("private", "1980-05-01"), encounters=encs)
    assert cov["relationship"]["coding"][0]["code"] == "self"
    assert "policyHolder" not in cov


def test_jp_dependent_child_is_a_child_from_birth() -> None:
    patient = _patient("dependent", "2023-10-12", country="JP", **_MOTHER)
    [cov] = _coverages(patient, "JP", encounters=_BIRTH_STAY)
    assert cov["period"]["start"] == "2023-10-12"
    assert cov["relationship"]["coding"][0]["code"] == "child"
    assert cov["subscriber"] == {"display": "Jane Smith"}


def test_jp_minor_policy_holder_role_is_japanese() -> None:
    encs = [{"admission_datetime": "2025-06-01T10:00:00"}]
    [cov] = _coverages(_patient("employee", "2012-05-01", country="JP"), "JP", encounters=encs)
    assert cov["relationship"]["coding"][0]["code"] == "child"
    assert cov["policyHolder"] == {"display": "保護者"}
