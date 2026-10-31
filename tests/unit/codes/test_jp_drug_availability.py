"""JP patients get drugs marketed in Japan, with YJ codes (Issue #2136)."""

from __future__ import annotations

import pytest

from clinosim.codes import get_system_uri
from clinosim.codes.drugs import jp_drug_code
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
    ("name", "route", "prefix"),
    [
        ("hydrochlorothiazide 25mg", "PO", "2132004"),
        ("rosuvastatin 10mg", "PO", "2189017"),
        ("ezetimibe 10mg", "PO", "2189018"),
        ("empagliflozin 10mg", "PO", "3969023"),
        ("leuprolide 3.75mg", "SC", "2499407"),
        ("acamprosate 666mg", "PO", "1190022"),
        ("semaglutide 1mg", "SC", "2499418"),
        ("disulfiram 250mg", "PO", "3939001"),
        ("liraglutide 1.2mg", "SC", "2499410"),
        ("Methyldopa 250mg", "PO", "2145001"),
        ("Cefditoren pivoxil 100mg", "PO", "6132015"),
        ("Ofloxacin ophthalmic drops", "OPH", "1319722"),
        ("Cyclopentolate 1% eye drops", "OPH", "1311701"),
        ("Betahistine 12mg", "PO", "1339005"),
        ("Eperisone 50mg", "PO", "1249009"),
        ("Oxybuprocaine 0.4% eye drops", "OPH", "1313700"),
        ("Naphazoline nasal drops", "nasal", "1324704"),
        ("nalmefene 10mg", "PO", "1190025"),
        ("ケイツーシロップ (メナテトレノン 2 mg 経口)", "PO", "3160002"),
        ("Tegafur-Gimeracil-Oteracil 80mg", "PO", "4229101"),
    ],
)
def test_jp_codes_for_marketed_drugs(name: str, route: str, prefix: str) -> None:
    # A full YJ product code of the ingredient (the first seven characters),
    # under the YJ URI (Issue #2347).
    concept, _ = _resolve_medication_concept(name, order_code="", country="JP", route=route)
    coding = concept["coding"][0]
    assert coding["code"].startswith(prefix) and len(coding["code"]) == 12
    assert coding["system"] == get_system_uri("yj")


def test_acetaminophen_code_follows_the_route() -> None:
    assert jp_drug_code("acetaminophen", "PO") == "1141007F3023"  # カロナール錠500
    assert jp_drug_code("acetaminophen", "IV") == "1141400A2020"  # アセリオ静注液1000mgバッグ
