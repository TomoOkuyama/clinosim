"""JP patients get drugs marketed in Japan, with YJ codes (Issue #2136)."""

from __future__ import annotations

import pytest
import yaml

from clinosim.modules.encounter.protocol import load_encounter_condition
from clinosim.modules.output.fhir_r4.medications.medications import _resolve_medication_concept
from clinosim.modules.patient.activator import _derive_home_medications
from clinosim.types.patient import ChronicCondition

pytestmark = pytest.mark.unit


def _drugs(code: str, country: str, n: int = 400) -> set[str]:
    names: set[str] = set()
    for i in range(n):
        meds = _derive_home_medications(
            [ChronicCondition(code=code, severity_score=0.5)], patient_id=f"P{i}", country=country, patient_age=50
        )
        names |= {m.drug_name.lower() for m in meds}
    return names


def test_home_medications_respect_locale_exclude() -> None:
    assert "fluoxetine" not in _drugs("F32", "JP")
    assert "fluoxetine" in _drugs("F32", "US")
    assert "naltrexone" not in _drugs("F10", "JP")
    assert "nalmefene" in _drugs("F10", "JP")
    assert "nalmefene" not in _drugs("F10", "US")


def test_activation_passes_the_patient_country() -> None:
    import inspect

    from clinosim.modules.patient import activator

    src = inspect.getsource(activator.activate_patient)
    assert 'country="US"' not in src.split("_derive_home_medications(", 1)[1].split(")", 1)[0]


@pytest.mark.parametrize(
    ("condition", "us_name", "jp_name"),
    [
        ("vertigo", "Meclizine", "Betahistine"),
        ("low_back_pain", "Cyclobenzaprine", "Eperisone"),
        ("eye_foreign_body", "Proparacaine", "Oxybuprocaine"),
        ("epistaxis", "Oxymetazoline", "Naphazoline"),
        ("uti_uncomplicated", "Nitrofurantoin", "Cefcapene pivoxil"),
    ],
)
def test_ed_treatments_use_jp_alternatives(condition: str, us_name: str, jp_name: str) -> None:
    tx = [t for t in load_encounter_condition(condition)["treatment"] if us_name in t["name"]]
    assert tx and tx[0]["locale_name"]["jp"].startswith(jp_name)


def test_phenazopyridine_is_not_given_in_jp() -> None:
    tx = [t for t in load_encounter_condition("uti_uncomplicated")["treatment"] if "Phenazopyridine" in t["name"]]
    assert tx and "JP" in tx[0]["locale_exclude"]


@pytest.mark.parametrize(
    ("name", "code"),
    [
        ("hydrochlorothiazide 25mg", "2132004"),
        ("rosuvastatin 10mg", "2189017"),
        ("ezetimibe 10mg", "2189018"),
        ("empagliflozin 10mg", "3969023"),
        ("leuprolide 3.75mg", "2499407"),
        ("acamprosate 666mg", "1190022"),
        ("semaglutide 1mg", "2499418"),
        ("disulfiram 250mg", "3939001"),
        ("liraglutide 1.2mg", "2499410"),
        ("Methyldopa 250mg", "2145001"),
        ("Cefditoren pivoxil 100mg", "6132015"),
        ("Ofloxacin ophthalmic drops", "1319722"),
        ("Cyclopentolate 1% eye drops", "1311701"),
        ("Betahistine 12mg", "1339005"),
        ("Eperisone 50mg", "1249009"),
        ("Oxybuprocaine 0.4% eye drops", "1313700"),
        ("Naphazoline nasal drops", "1324704"),
        ("nalmefene 10mg", "1190025"),
        ("ケイツーシロップ (メナテトレノン 2 mg 経口)", "3160002"),
        ("Tegafur-Gimeracil-Oteracil 80mg", "4229101"),
    ],
)
def test_jp_codes_for_marketed_drugs(name: str, code: str) -> None:
    concept, _ = _resolve_medication_concept(name, order_code="", country="JP")
    assert concept["coding"][0]["code"] == code


def test_acetaminophen_is_mapped_once() -> None:
    text = open("clinosim/locale/jp/code_mapping_drug.yaml", encoding="utf-8").read()
    keys = [line.split(":")[0].strip().strip('"') for line in text.splitlines() if line and not line.startswith("#")]
    assert keys.count("Acetaminophen") == 1
    assert yaml.safe_load(text)["Acetaminophen"]
