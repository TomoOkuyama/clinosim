"""Issue #2614: US medications are coded at RxNorm SCD level (strength + dose form)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from clinosim.codes import lookup as code_lookup
from clinosim.codes.drugs import rxnorm_scd_code
from clinosim.datafiles import load_data_yaml

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[3]


def _name(rxcui: str | None) -> str:
    return code_lookup("rxnorm", rxcui or "", "en")


def test_dose_and_route_select_the_clinical_drug() -> None:
    assert _name(rxnorm_scd_code("Amlodipine", "PO", 5, "mg")) == "amlodipine 5 MG Oral Tablet"
    assert _name(rxnorm_scd_code("Acetaminophen", "PO", 500, "mg")) == "acetaminophen 500 MG Oral Tablet"
    assert _name(rxnorm_scd_code("Acetaminophen", "IV", 1, "g")) == "100 ML acetaminophen 10 MG/ML Injection"
    assert _name(rxnorm_scd_code("Ondansetron", "IV", 4, "mg")) == "2 ML ondansetron 2 MG/ML Injection"


def test_vitamin_d_in_international_units_selects_the_cholecalciferol_tablet() -> None:
    assert rxnorm_scd_code("Vitamin D", "PO", 1000, "IU") == "199362"  # cholecalciferol 0.025 MG Oral Tablet


def test_a_combination_matches_its_first_ingredient_then_its_total() -> None:
    # 250 mcg fluticasone = the 250/50 inhaler; 4.5 g piperacillin/tazobactam = 4 g / 0.5 g.
    assert rxnorm_scd_code("Fluticasone/Salmeterol", "INH", 250, "mcg") == "896209"
    assert "piperacillin 4000 MG / tazobactam 500 MG" in _name(
        rxnorm_scd_code("Piperacillin/Tazobactam", "IV", 4.5, "g")
    )


def test_a_dose_of_several_units_takes_the_fewest() -> None:
    # 20 mg of a drug sold as 10 mg and 20 mg tablets is one 20 mg tablet.
    assert _name(rxnorm_scd_code("Atorvastatin", "PO", 20, "mg")) == "atorvastatin 20 MG Oral Tablet"


def test_no_product_fits_weight_based_doses_or_unknown_drugs() -> None:
    assert rxnorm_scd_code("Trastuzumab", "IV", 6, "mg/kg") is None
    assert rxnorm_scd_code("Amlodipine", "PO", 7, "mg") is None
    assert rxnorm_scd_code("Not a drug", "PO", 5, "mg") is None


def test_every_clinical_drug_is_current_and_shown_by_its_rxnorm_name() -> None:
    snapshot = {
        c["code"]: c
        for c in json.loads((_ROOT / "clinosim/codes/authoritative/rxnorm_rxnav_snapshot.json").read_text())["concept"]
    }
    table = load_data_yaml(_ROOT / "clinosim/codes/data/rxnorm_scd.yaml")["drugs"]
    problems = []
    for drug, routes in table.items():
        for route, entries in routes.items():
            for e in entries:
                c = snapshot.get(e["rxcui"])
                if not c or c["status"] != "Active" or c["tty"] != "SCD":
                    problems.append((drug, route, e["rxcui"], "not a current SCD"))
                elif code_lookup("rxnorm", e["rxcui"], "en") != c["name"]:
                    problems.append((drug, route, e["rxcui"], "display is not the RxNorm name"))
    assert not problems, problems[:10]


def test_us_medication_request_codes_the_scd_before_the_ingredient() -> None:
    from clinosim.modules.output.fhir_r4.medications.medications import _apply_rxnorm_scd

    mr = {
        "resourceType": "MedicationRequest",
        "medicationCodeableConcept": {
            "text": "Amlodipine",
            "coding": [
                {"system": "http://www.nlm.nih.gov/research/umls/rxnorm", "code": "17767", "display": "amlodipine"}
            ],
        },
        "dosageInstruction": [
            {"route": {"text": "PO"}, "doseAndRate": [{"doseQuantity": {"value": 5.0, "unit": "mg"}}]}
        ],
    }
    _apply_rxnorm_scd(mr, "US")
    assert [c["code"] for c in mr["medicationCodeableConcept"]["coding"]] == ["197361", "17767"]
    jp = json.loads(json.dumps(mr))
    jp["medicationCodeableConcept"]["coding"] = jp["medicationCodeableConcept"]["coding"][1:]
    _apply_rxnorm_scd(jp, "JP")
    assert [c["code"] for c in jp["medicationCodeableConcept"]["coding"]] == ["17767"]
