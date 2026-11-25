"""Unit tests for the used-codes catalog accumulator (Issue #3762)."""

from __future__ import annotations

import json

from clinosim.modules.output.fhir_r4.lib.used_codes import (
    METADATA_KEY,
    UsedCodesCatalog,
    catalog_path_for,
    register_in_cif_metadata,
)

RX = "http://www.nlm.nih.gov/research/umls/rxnorm"
LOINC = "http://loinc.org"
SNOMED = "http://snomed.info/sct"


def _mr(rid: str, patient: str, codes: list[tuple[str, str]], route: str | None, unit: str = "mg") -> dict:
    dosage: dict = {
        "doseAndRate": [{"doseQuantity": {"value": 1, "system": "http://unitsofmeasure.org", "code": unit}}]
    }
    if route:
        dosage["route"] = {"coding": [{"system": SNOMED, "code": "26643006", "display": "Oral route"}], "text": route}
    return {
        "resourceType": "MedicationRequest",
        "id": rid,
        "subject": {"reference": f"Patient/{patient}"},
        "medicationCodeableConcept": {
            "text": "Drug",
            "coding": [{"system": RX, "code": c, "display": d} for c, d in codes],
        },
        "dosageInstruction": [dosage],
    }


def _by_key(cat: UsedCodesCatalog) -> dict[tuple, dict]:
    return {(x["kind"], x["system"], x["code"], x.get("route")): x for x in cat.lines()}


def test_each_code_listed_once_with_counts_and_patients() -> None:
    cat = UsedCodesCatalog()
    cat.observe(_mr("a", "p1", [("100", "SCD one"), ("10", "Ingredient")], "PO"))
    cat.observe(_mr("b", "p1", [("100", "SCD one"), ("10", "Ingredient")], "PO"))
    cat.observe(_mr("c", "p2", [("100", "SCD one"), ("10", "Ingredient")], "PO"))
    got = _by_key(cat)
    assert set(got) == {("medication", RX, "100", "PO"), ("medication", RX, "10", "PO")}
    scd = got[("medication", RX, "100", "PO")]
    assert scd["count"] == 3
    assert scd["patients"] == 2
    assert scd["dose_units"] == ["mg"]
    assert scd["co_coded"] == [{"system": RX, "code": "10", "display": "Ingredient"}]
    assert scd["route_coding"] == [{"system": SNOMED, "code": "26643006", "display": "Oral route"}]


def test_medication_is_keyed_by_route_text_and_missing_route_is_null() -> None:
    cat = UsedCodesCatalog()
    cat.observe(_mr("a", "p1", [("10", "Ing")], "PO"))
    cat.observe(_mr("b", "p1", [("10", "Ing")], "IV"))
    cat.observe(_mr("c", "p1", [("10", "Ing")], None))
    assert {x["route"] for x in cat.lines()} == {"PO", "IV", None}
    assert all("route" in x for x in cat.lines())


def test_observation_kinds_units_ranges_components_and_specimen() -> None:
    cat = UsedCodesCatalog()
    lab = {
        "resourceType": "Observation",
        "id": "lab-1",
        "subject": {"reference": "Patient/p1"},
        "category": [{"coding": [{"code": "laboratory"}]}],
        "code": {"coding": [{"system": LOINC, "code": "1920-8", "display": "AST"}]},
        "valueQuantity": {"value": 3, "system": "http://unitsofmeasure.org", "code": "U/L"},
        "referenceRange": [{"low": {"value": 10, "code": "U/L"}, "high": {"value": 40, "code": "U/L"}, "text": "t"}],
        "specimen": {"reference": "Specimen/spec-1"},
    }
    cat.observe(lab)  # the Observation precedes its Specimen: resolved at end_bundle
    cat.observe(
        {"resourceType": "Specimen", "id": "spec-1", "type": {"coding": [{"system": SNOMED, "code": "119297000"}]}}
    )
    bp = {
        "resourceType": "Observation",
        "id": "vs-1",
        "subject": {"reference": "Patient/p1"},
        "category": [{"coding": [{"code": "vital-signs"}]}],
        "code": {"coding": [{"system": LOINC, "code": "85354-9", "display": "BP panel"}]},
        "component": [
            {
                "code": {"coding": [{"system": LOINC, "code": "8480-6", "display": "Systolic"}]},
                "valueQuantity": {"code": "mm[Hg]"},
            }
        ],
    }
    score = {
        "resourceType": "Observation",
        "id": "gcs-1",
        "subject": {"reference": "Patient/p1"},
        "category": [{"coding": [{"code": "survey"}]}],
        "code": {"coding": [{"system": LOINC, "code": "9269-2", "display": "GCS"}]},
        "valueInteger": 15,
    }
    social = {
        "resourceType": "Observation",
        "id": "alc-1",
        "subject": {"reference": "Patient/p1"},
        "category": [{"coding": [{"code": "social-history"}]}],
        "code": {"coding": [{"system": LOINC, "code": "11331-6"}]},
        "valueCodeableConcept": {"text": "x"},
    }
    for r in (bp, score, social):
        cat.observe(r)
    cat.end_bundle()
    got = _by_key(cat)
    lab_line = got[("lab", LOINC, "1920-8", None)]
    assert lab_line["units"] == ["U/L"]
    assert lab_line["value_types"] == ["Quantity"]
    assert lab_line["reference_ranges"] == [{"low": 10, "high": 40, "unit": "U/L", "text": "t"}]
    assert lab_line["specimens"] == [{"system": SNOMED, "code": "119297000"}]
    assert got[("vital-sign", LOINC, "85354-9", None)]["components"] == [
        {"system": LOINC, "code": "8480-6", "display": "Systolic", "unit": "mm[Hg]"}
    ]
    assert ("nursing-score", LOINC, "9269-2", None) in got
    assert ("observation", LOINC, "11331-6", None) in got


def test_imaging_diagnosis_procedure_document_vaccine_allergen_and_organism() -> None:
    cat = UsedCodesCatalog()
    subj = {"reference": "Patient/p1"}
    cat.observe(
        {
            "resourceType": "ImagingStudy",
            "id": "i1",
            "subject": subj,
            "modality": [{"system": "dcm", "code": "CR", "display": "X-ray"}],
            "series": [
                {"modality": {"system": "dcm", "code": "CR"}, "bodySite": {"system": SNOMED, "code": "51185008"}}
            ],
            "procedureCode": [{"coding": [{"system": LOINC, "code": "42272-5", "display": "XR Chest"}]}],
        }
    )
    cat.observe(
        {
            "resourceType": "Condition",
            "id": "c1",
            "subject": subj,
            "code": {"coding": [{"system": "icd", "code": "J18.9"}]},
        }
    )
    cat.observe(
        {
            "resourceType": "Procedure",
            "id": "pr1",
            "subject": subj,
            "code": {"coding": [{"system": "cpt", "code": "96413"}]},
        }
    )
    cat.observe({"resourceType": "Procedure", "id": "pr2", "subject": subj, "code": {"text": "text only"}})
    cat.observe(
        {
            "resourceType": "DocumentReference",
            "id": "d1",
            "subject": subj,
            "type": {"coding": [{"system": LOINC, "code": "11488-4"}]},
        }
    )
    cat.observe(
        {
            "resourceType": "Immunization",
            "id": "v1",
            "patient": subj,
            "vaccineCode": {"coding": [{"system": "cvx", "code": "20"}]},
        }
    )
    cat.observe(
        {
            "resourceType": "AllergyIntolerance",
            "id": "a1",
            "patient": subj,
            "code": {"coding": [{"system": SNOMED, "code": "764146007"}]},
        }
    )
    org = {
        "resourceType": "Observation",
        "id": "o1",
        "subject": subj,
        "identifier": [{"system": "urn:clinosim:identifier:mb-organism-observation-key", "value": "k"}],
        "category": [{"coding": [{"code": "laboratory"}]}],
        "code": {"coding": [{"system": LOINC, "code": "600-7"}]},
        "valueCodeableConcept": {"coding": [{"system": SNOMED, "code": "3092008"}]},
    }
    no_growth = json.loads(json.dumps(org))
    no_growth["valueCodeableConcept"] = {"coding": [{"system": SNOMED, "code": "264868006"}]}
    cat.observe(org)
    cat.observe(no_growth)
    got = _by_key(cat)
    study = got[("imaging", LOINC, "42272-5", None)]
    assert (
        study["modalities"] == [{"system": "dcm", "code": "CR", "display": "X-ray"}, {"system": "dcm", "code": "CR"}]
        or study["modalities"]
    )
    assert study["body_sites"] == [{"system": SNOMED, "code": "51185008"}]
    for key in [
        ("diagnosis", "icd", "J18.9", None),
        ("procedure", "cpt", "96413", None),
        ("document-type", LOINC, "11488-4", None),
        ("vaccine", "cvx", "20", None),
        ("allergen", SNOMED, "764146007", None),
        ("organism", SNOMED, "3092008", None),
    ]:
        assert key in got, key
    assert not any(k[2] == "264868006" for k in got)
    assert len([k for k in got if k[0] == "procedure"]) == 1


def test_writer_and_metadata_registration(tmp_path) -> None:
    cat = UsedCodesCatalog()
    cat.observe(_mr("a", "p1", [("10", "Ing")], "PO"))
    out = catalog_path_for(str(tmp_path / "fhir_r4"))
    assert out == str(tmp_path / "catalog" / "codes-used.ndjson")
    assert cat.write(out) == 1
    rows = [json.loads(line) for line in open(out, encoding="utf-8")]
    assert rows[0]["code"] == "10"
    cif = tmp_path / "cif"
    cif.mkdir()
    (cif / "metadata.json").write_text(json.dumps({"country": "US"}), encoding="utf-8")
    register_in_cif_metadata(str(cif), out)
    assert json.loads((cif / "metadata.json").read_text(encoding="utf-8"))[METADATA_KEY] == "catalog/codes-used.ndjson"
    # no metadata file: left alone
    register_in_cif_metadata(str(tmp_path / "none"), out)
