"""HL7 vocabularies resolve by code from the code-keyed registry (Issue #2264).

The English-keyed Japanese table (``hl7-display-ja.yaml``) and
``_localize_display`` are retired. Every HL7 code the Encounter, Observation,
Condition and Organization builders emit is registered in a
``codes/data/hl7-*.yaml`` file, and the emitted shape follows the dual-slot
rule of the code-mapping spec (§5.3): ``coding.display`` is the HL7 English
display in every locale, and the Japanese label goes in ``text``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from clinosim.codes import display
from clinosim.modules.output.fhir_r4.encounters.encounter import _build_encounter
from clinosim.modules.output.fhir_r4.encounters.facility import _build_facility_bundle
from clinosim.modules.output.fhir_r4.lib.common import _social_category, make_participant

pytestmark = pytest.mark.unit

# English displays verified on tx.fhir.org CodeSystem/$lookup (HL7 Terminology).
_THO_DISPLAYS = {
    "hl7-v3-actcode": {
        "AMB": "ambulatory",
        "IMP": "inpatient encounter",
        "EMER": "emergency",
        "ACUTE": "inpatient acute",
    },
    "hl7-v3-actpriority": {"EM": "emergency", "UR": "urgent", "R": "routine", "EL": "elective"},
    "hl7-observation-category": {
        "laboratory": "Laboratory",
        "vital-signs": "Vital Signs",
        "social-history": "Social History",
    },
    "hl7-condition-category": {"encounter-diagnosis": "Encounter Diagnosis", "problem-list-item": "Problem List Item"},
    "hl7-v3-participationtype": {"ATND": "attender", "ADM": "admitter", "DIS": "discharger"},
    "hl7-diagnosis-role": {"AD": "Admission diagnosis", "DD": "Discharge diagnosis", "CM": "Comorbidity diagnosis"},
    "hl7-organization-type": {"prov": "Healthcare Provider", "dept": "Hospital Department"},
    "hl7-observation-interpretation": {
        "N": "Normal",
        "H": "High",
        "L": "Low",
        "HH": "Critical high",
        "LL": "Critical low",
        "AA": "Critical abnormal",
        "S": "Susceptible",
        "I": "Intermediate",
        "R": "Resistant",
    },
}

_CODES_DATA = Path(__file__).resolve().parents[2] / "clinosim" / "codes" / "data"


@pytest.mark.parametrize(
    ("system", "code"), [(s, c) for s, codes in sorted(_THO_DISPLAYS.items()) for c in sorted(codes)]
)
def test_emitted_hl7_code_has_tho_english_and_a_japanese_display(system: str, code: str) -> None:
    assert display(system, code, "en") == _THO_DISPLAYS[system][code]
    ja = display(system, code, "ja")
    assert ja and ja != _THO_DISPLAYS[system][code]


def test_english_keyed_japanese_table_is_retired() -> None:
    assert not (_CODES_DATA / "hl7-display-ja.yaml").exists()


def _inpatient(country: str) -> dict:
    enc = {
        "encounter_id": "ENC-1",
        "encounter_type": "inpatient",
        "department_id": "internal_medicine",
        "priority": "EM",
        "admission_datetime": "2026-01-01T09:00:00",
        "discharge_datetime": "2026-01-05T10:00:00",
        "attending_physician": "DR-IM-001",
    }
    return _build_encounter(
        enc,
        "patient-1",
        primary_dx_code="J18.9",
        country=country,
        icu_transferred_day=1,
        chronic_condition_codes=["I10"],
    )


def test_jp_encounter_codings_carry_english_display_and_japanese_text() -> None:
    r = _inpatient("JP")
    # Encounter.class is a Coding (no text slot): English display only.
    assert r["class"]["display"] == "inpatient encounter"
    assert [h["class"]["display"] for h in r["classHistory"]] == ["inpatient encounter", "inpatient acute"]
    assert r["priority"]["coding"][0]["display"] == "emergency"
    assert r["priority"]["text"] == "緊急"
    uses = {d["use"]["coding"][0]["code"]: d["use"] for d in r["diagnosis"]}
    assert uses["DD"]["coding"][0]["display"] == "Discharge diagnosis"
    assert uses["DD"]["text"] == "退院時診断"
    assert uses["CM"]["text"] == "併存疾患"


def test_us_encounter_has_no_japanese() -> None:
    import json

    r = _inpatient("US")
    assert r["priority"] == {
        "coding": [
            {"system": "http://terminology.hl7.org/CodeSystem/v3-ActPriority", "code": "EM", "display": "emergency"}
        ],
        "text": "emergency",
    }
    assert json.dumps(r, ensure_ascii=False).isascii()


def test_participant_and_social_category_follow_dual_slot() -> None:
    p = make_participant("ADM", "DR-1", "JP")
    assert p["type"][0]["coding"][0]["display"] == "admitter"
    assert p["type"][0]["text"] == "入院担当医"
    cat = _social_category("JP")[0]
    assert cat["coding"][0]["display"] == "Social History"
    assert cat["text"] == "社会歴"


@pytest.mark.parametrize(
    ("country", "er", "opd", "operating_room"),
    [("US", "Emergency Room", "Outpatient Clinic", "Operating Room"), ("JP", "救急外来", "外来", "手術室")],
)
def test_care_area_locations_are_named_not_area(country: str, er: str, opd: str, operating_room: str) -> None:
    config = {
        "available_departments": ["emergency_medicine", "primary_care", "general_surgery"],
        "wards": {"emergency_medicine": ["ER"], "primary_care": ["OPD"]},
        "resource_capacity": {"inpatient_beds": 50, "operating_rooms": 1},
    }
    locations = {
        e["resource"]["id"]: e["resource"]
        for e in _build_facility_bundle(config, country)["entry"]
        if e["resource"]["resourceType"] == "Location"
    }
    assert locations["loc-ward-ER"]["name"] == er
    assert locations["loc-ward-OPD"]["name"] == opd
    assert locations["loc-or-1"]["type"] == [{"text": operating_room}]
    org_types = {
        e["resource"]["id"]: e["resource"]["type"][0]
        for e in _build_facility_bundle(config, country)["entry"]
        if e["resource"]["resourceType"] == "Organization"
    }
    assert org_types["hospital-main"]["coding"][0]["display"] == "Healthcare Provider"
