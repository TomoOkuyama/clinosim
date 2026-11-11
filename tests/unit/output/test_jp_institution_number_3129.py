"""JP 医療機関コード in the 10-digit format (Issue #3129).

The JP-CLINS JP_eCS_InstitutionNumber extension requires
``^[0-4][0-9][1-3][0-9]{7}$`` (constraint valid-value-institutionNumberExtension):
2-digit prefecture, 1-digit 点数表番号 (1 医科), 7-digit code. The hospital's
code (in locale YAML) is used for the extension and for the hospital
Organization's identifier; the external hospitals' codes follow the same
format and match their prefecture.
"""

from __future__ import annotations

import re

import pytest

from clinosim.codes.prefectures import prefecture_code
from clinosim.locale.loader import load_external_organizations, load_facility_identity
from clinosim.modules.output.fhir_r4.lib.ecs_extensions import build_ecs_institution_extension

pytestmark = pytest.mark.unit

_ECS_RULE = re.compile(r"^[0-4][0-9][1-3][0-9]{7}$")


def _medical(code: str, prefecture: str) -> None:
    assert _ECS_RULE.match(code), code
    assert code[:2] == prefecture_code(prefecture), (code, prefecture)
    assert code[2] == "1", code  # 点数表番号 1: 医科


def test_the_hospital_code_is_a_10_digit_medical_code_of_its_prefecture() -> None:
    hospital = load_facility_identity("JP")
    _medical(hospital["institution_code"], hospital["prefecture"])


def test_the_extension_carries_the_hospital_code() -> None:
    ext = build_ecs_institution_extension("JP")
    assert ext["valueIdentifier"]["value"] == load_facility_identity("JP")["institution_code"]


def test_the_hospital_organization_carries_the_same_code() -> None:
    from clinosim.modules.output.fhir_r4.encounters.facility import _build_facility_bundle

    entries = _build_facility_bundle({"resource_capacity": {"inpatient_beds": 200}}, "JP")["entry"]
    org = next(e["resource"] for e in entries if e["resource"]["id"] == "hospital-main")
    assert org["identifier"][0]["value"] == load_facility_identity("JP")["institution_code"]


@pytest.mark.parametrize("entry", load_external_organizations("JP"), ids=lambda e: e["id"])
def test_every_external_hospital_code_is_a_10_digit_medical_code(entry: dict) -> None:
    _medical(str(entry["institution_code"]), entry["address"]["prefecture"])
