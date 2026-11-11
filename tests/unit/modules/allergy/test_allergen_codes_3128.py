"""Allergen codes are active in their system and, for JP, members of the
JP-CLINS JP_AllergyIntolerance_VS (Issue #3128)."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from clinosim.codes import get_system_uri
from clinosim.codes import lookup as code_lookup
from clinosim.modules.allergy.engine import load_allergen_config
from clinosim.modules.output.fhir_r4.conditions.allergy_intolerance import _bb_allergy_intolerances
from clinosim.modules.output.fhir_r4.post_process.profile import _apply_jp_clins_profile
from clinosim.types.allergy import Allergy, AllergyReaction

pytestmark = pytest.mark.unit

_AUTH = Path(__file__).resolve().parents[4] / "clinosim" / "codes" / "authoritative"
_ECS = "http://jpfhir.jp/fhir/eCS/StructureDefinition/JP_AllergyIntolerance_eCS"
# JP_AllergyIntolerance_VS|2023.9.25 (jpfhir-terminology 2.2606.0) includes these four CodeSystems.
_JP_VS_SYSTEMS = {
    "http://jpfhir.jp/fhir/core/CodeSystem/JP_JfagyFoodAllergen_CS",
    "http://jpfhir.jp/fhir/core/CodeSystem/JP_JfagyNonFoodNonMedicationAllergen_CS",
    "http://jpfhir.jp/fhir/core/CodeSystem/GCM/JP_JfagyMedicationAllergen_CS",
    "http://jpfhir.jp/fhir/core/CodeSystem/YCM/JP_JfagyMedicationAllergen_CS",
}


def _snapshot(name: str) -> dict[tuple[str, str], dict]:
    data = json.loads((_AUTH / name).read_text(encoding="utf-8"))
    return {(c.get("system", "http://snomed.info/sct"), c["code"]): c for c in data["concept"]}


def _entries() -> list[tuple[str, dict]]:
    return [(cat, e) for cat, entries in load_allergen_config()["allergens"].items() for e in entries]


def test_every_snomed_code_is_active_in_the_international_edition() -> None:
    snomed = _snapshot("snomed_allergy_tx.json")
    cfg = load_allergen_config()
    codes = {cfg["nka"]["allergen_code"]}
    for _cat, e in _entries():
        codes.add(e["allergen_code"])
        codes |= {r["manifestation_snomed"] for r in e["common_reactions"]}
    for code in sorted(codes):
        concept = snomed.get(("http://snomed.info/sct", code))
        assert concept is not None, f"{code} not verified on tx.fhir.org"
        assert concept["inactive"] is False, code


def test_every_allergen_has_a_jp_value_set_code_with_its_display() -> None:
    jfagy = _snapshot("jfagy_jpfhir_terminology.json")
    for _cat, e in _entries():
        jp = e["country_codes"]["JP"]
        uri = get_system_uri(jp["system"])
        assert uri in _JP_VS_SYSTEMS, e["allergen_code"]
        concept = jfagy.get((uri, jp["code"]))
        assert concept is not None, f"{jp['code']} not in the JFAGY snapshot"
        assert code_lookup(jp["system"], jp["code"], "ja") == concept["display"]


def _allergy(code: str, category: str) -> Allergy:
    return Allergy(
        allergy_id="1",
        allergen_code=code,
        category=category,
        criticality="high",
        verification_status="confirmed",
        clinical_status="active",
        onset_date=None,
        reactions=[AllergyReaction(manifestation_snomed="271807003", severity="mild")],
    )


def _ctx(allergies: list, country: str) -> SimpleNamespace:
    return SimpleNamespace(
        record={"patient": {"allergies": allergies, "patient_id": "pt1"}, "extensions": {}},
        country=country,
        patient_id="pt1",
    )


@pytest.mark.parametrize("country", ["US", "JP"])
def test_each_allergen_is_coded_in_the_countrys_system(country: str) -> None:
    for cat, e in _entries():
        resource = _bb_allergy_intolerances(_ctx([_allergy(e["allergen_code"], cat)], country))[0]
        codings = resource["code"]["coding"]
        assert len(codings) == 1
        if country == "US":
            assert codings[0] == {
                "system": "http://snomed.info/sct",
                "code": e["allergen_code"],
                "display": code_lookup("snomed-ct", e["allergen_code"], "en"),
            }
        else:
            jp = e["country_codes"]["JP"]
            assert codings[0]["system"] in _JP_VS_SYSTEMS
            assert (codings[0]["code"], codings[0]["display"]) == (
                jp["code"],
                code_lookup(jp["system"], jp["code"], "ja"),
            )
            assert resource["code"]["text"] == code_lookup("snomed-ct", e["allergen_code"], "ja")


def test_jp_ecs_profile_only_on_value_set_codes() -> None:
    nka = Allergy(
        allergy_id="nka",
        allergen_code="716186003",
        category="",
        criticality="unable-to-assess",
        verification_status="confirmed",
        clinical_status="active",
        onset_date=None,
        reactions=[],
        is_nka=True,
    )
    no_allergy, egg = _bb_allergy_intolerances(_ctx([nka, _allergy("303300008", "food")], "JP"))
    for resource in (no_allergy, egg):
        _apply_jp_clins_profile(resource, "JP")
    # No Known Allergy has no JFAGY code: it keeps JP Core (example binding) only.
    assert _ECS not in no_allergy["meta"]["profile"]
    assert no_allergy["meta"]["profile"] == ["http://jpfhir.jp/fhir/core/StructureDefinition/JP_AllergyIntolerance"]
    assert _ECS in egg["meta"]["profile"]
