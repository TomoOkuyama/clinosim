"""Issue #2265: UCUM, DICOM, JIS X 0401, JP document / allergen / medication
CodeSystems and US identifier systems come from the code registry."""

from __future__ import annotations

from pathlib import Path

import pytest

from clinosim.codes import get_system_uri, system_key_for_uri
from clinosim.codes.prefectures import prefecture_code
from clinosim.codes.ucum import ucum_code, ucum_quantity

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[2] / "clinosim"

# URIs that emitters used to hard-code; each now resolves through the registry.
_REGISTERED = {
    "jpfhir-doc-typecodes": "http://jpfhir.jp/fhir/Common/CodeSystem/doc-typecodes",
    "jpfhir-doc-subtypecodes": "http://jpfhir.jp/fhir/Common/CodeSystem/doc-subtypecodes",
    "jpfhir-doc-section": "http://jpfhir.jp/fhir/clins/CodeSystem/document-section",
    "jpfhir-eCheckup-section": "http://jpfhir.jp/fhir/eCheckup/CodeSystem/section-code",
    "jpfhir-echeckup-doc-typecodes": "http://jpfhir.jp/fhir/eCheckup/CodeSystem/doc-typecodes",
    "jp-document-codes": "http://jpfhir.jp/fhir/core/CodeSystem/JP_DocumentCodes_CS",
    "jp-jfagy-food-allergen": "http://jpfhir.jp/fhir/core/CodeSystem/JP_JfagyFoodAllergen_CS",
    "jp-jfagy-medication-allergen": "http://jpfhir.jp/fhir/core/CodeSystem/YCM/JP_JfagyMedicationAllergen_CS",
    "jp-jfagy-nonfood-nonmedication-allergen": (
        "http://jpfhir.jp/fhir/core/CodeSystem/JP_JfagyNonFoodNonMedicationAllergen_CS"
    ),
    "jp-condition-severity": "http://jpfhir.jp/fhir/core/CodeSystem/JP_ConditionSeverity_CS",
    "jp-clins-medication-usage-uncoded": "http://jpfhir.jp/fhir/clins/CodeSystem/JP_CLINS_MedicationUsage_Uncoded_CS",
    "jp-medication-usage-eprescription": "http://jpfhir.jp/fhir/core/mhlw/CodeSystem/MedicationUsage_ePrescription",
    "jp-medication-ingredient-strength-type": (
        "http://jpfhir.jp/fhir/core/mhlw/CodeSystem/MedicationIngredientStrengthStrengthType"
    ),
    "dicom-modality": "http://dicom.nema.org/resources/ontology/DCM",
    "ucum": "http://unitsofmeasure.org",
    "omb-race": "urn:oid:2.16.840.1.113883.6.238",
    "us-ssn": "http://hl7.org/fhir/sid/us-ssn",
    "us-npi": "http://hl7.org/fhir/sid/us-npi",
}


@pytest.mark.parametrize(("key", "uri"), sorted(_REGISTERED.items()))
def test_uri_is_registered(key: str, uri: str) -> None:
    assert get_system_uri(key) == uri


def test_builtin_registrations_round_trip() -> None:
    for key in ("jp-document-codes", "jpfhir-doc-subtypecodes", "us-npi", "us-ssn"):
        assert system_key_for_uri(get_system_uri(key)) == key


def test_no_emitter_hard_codes_a_registered_uri() -> None:
    offenders = []
    for path in sorted(_ROOT.rglob("*.py")):
        rel = path.relative_to(_ROOT).as_posix()
        # Prefix lists that name URI families, not code systems.
        if rel.startswith("codes/") or rel in (
            "audit/axes/jp_language.py",
            "modules/output/fhir_r4/post_process/strip.py",
        ):
            continue
        text = path.read_text(encoding="utf-8")
        offenders += [f"{rel}: {uri}" for uri in _REGISTERED.values() if f'"{uri}"' in text]
    assert not offenders, offenders


def test_prefecture_code() -> None:
    assert prefecture_code("東京都") == "13"
    assert prefecture_code("北海道") == "01"
    assert prefecture_code("Tokyo") == ""


def test_ucum_quantity_builds_every_quantity() -> None:
    assert ucum_quantity(1, "mL") == {"value": 1, "system": get_system_uri("ucum"), "unit": "mL", "code": "mL"}
    assert ucum_quantity(30, "日", code="d")["code"] == "d"
    assert ucum_quantity(30, "日", code="d")["unit"] == "日"
    assert ucum_code("mmHg") == "mm[Hg]"
