"""Encounter, document, shared-library and finishing-pass FHIR structure is
gated on the country profile, not on the country (Issue #3203).

``docs/design-guides/country-profile-spec.md`` §5: the per-resource finishing
passes (JP Core / JP-CLINS / US Core profile stacking, the JP-CLINS eCS
fields), the facility Organizations and Locations, the JP Core severity
coding and the JP-CLINS eCS institutional extensions run only when
``profile.uses(...)`` says the country's output applies the FHIR profile they
serve; the profile URLs come from ``clinosim/codes/data/fhir-profiles-*.yaml``.
The tests swap the profile's ``fhir_profiles`` list and check the structure
follows it.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

import clinosim.country_profile as cp
from clinosim.codes import data_table
from clinosim.modules.output.fhir_r4.builder import _finalize_resource
from clinosim.modules.output.fhir_r4.encounters.facility import _build_facility_bundle
from clinosim.modules.output.fhir_r4.lib.common import severity_coding
from clinosim.modules.output.fhir_r4.lib.ecs_extensions import attach_ecs_institutional_extensions

pytestmark = pytest.mark.unit

_CONFIG = {
    "available_departments": ["emergency_medicine", "primary_care", "general_surgery"],
    "wards": {"emergency_medicine": ["ER"], "primary_care": ["OPD"]},
    "resource_capacity": {"inpatient_beds": 50, "operating_rooms": 1},
}


def _jp_core(resource_type: str) -> list[str]:
    return list(data_table("fhir-profiles-jp-core")["profiles"][resource_type])


@pytest.fixture
def with_profiles(monkeypatch: pytest.MonkeyPatch) -> Callable[[tuple[str, ...]], None]:
    """Replace every country's ``fhir_profiles`` with the given list."""
    real = cp._profile

    def apply(names: tuple[str, ...]) -> None:
        monkeypatch.setattr(cp, "_profile", lambda code: real(code).model_copy(update={"fhir_profiles": names}))

    return apply


def _finalized(resource: dict, country: str) -> dict:
    _finalize_resource(resource, country, {})
    return resource


def _facility(country: str) -> list[dict]:
    return [e["resource"] for e in _build_facility_bundle(_CONFIG, country)["entry"]]


def test_jp_without_fhir_profiles_gets_base_fhir(with_profiles) -> None:
    with_profiles(())
    patient = _finalized({"resourceType": "Patient", "id": "P1"}, "JP")
    assert not patient.get("meta", {}).get("profile")
    for resource in _facility("JP"):
        assert "meta" not in resource, resource["id"]
    root = next(r for r in _facility("JP") if r["id"] == "hospital-main")
    assert "identifier" not in root and "telecom" not in root
    assert severity_coding("moderate", "JP")["coding"][0]["system"] == "http://snomed.info/sct"
    condition: dict = {"resourceType": "Condition", "id": "c1"}
    attach_ecs_institutional_extensions(condition, "JP")
    assert "extension" not in condition


def test_a_country_applying_the_jp_profiles_gets_their_structure(with_profiles) -> None:
    with_profiles(("jp_core", "jp_clins"))
    patient = _finalized({"resourceType": "Patient", "id": "P1"}, "US")
    assert patient["meta"]["profile"][: len(_jp_core("Patient"))] == _jp_core("Patient")
    assert not any("us/core" in url for url in patient["meta"]["profile"])
    resources = _facility("US")
    for loc in (r for r in resources if r["resourceType"] == "Location"):
        assert loc["meta"]["profile"] == _jp_core("Location"), loc["id"]
    root = next(r for r in resources if r["id"] == "hospital-main")
    assert root["meta"]["profile"][0] == _jp_core("Organization")[0]
    assert root["meta"]["lastUpdated"].endswith("Z")  # the country's own UTC offset
    assert severity_coding("moderate", "US")["coding"][0]["system"] != "http://snomed.info/sct"
    condition: dict = {"resourceType": "Condition", "id": "c1"}
    attach_ecs_institutional_extensions(condition, "US")
    assert condition["extension"]


def test_us_core_follows_the_profile(with_profiles) -> None:
    with_profiles(("us_core",))
    patient = _finalized({"resourceType": "Patient", "id": "P1"}, "JP")
    assert any("us/core" in url for url in patient["meta"]["profile"])
