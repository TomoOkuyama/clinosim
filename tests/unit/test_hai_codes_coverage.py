"""Smoke test: HAI condition + organism + specimen + culture codes resolve (PR-B)."""
from __future__ import annotations

import pytest

from clinosim.codes import lookup
from clinosim.modules.hai.engine import (
    load_hai_codes,
    load_hai_organisms,
    load_hai_specimens,
)


pytestmark = pytest.mark.unit


@pytest.mark.parametrize("hai_type", ["clabsi", "cauti", "vap"])
def test_hai_condition_codes_resolve(hai_type):
    cfg = load_hai_codes()["hai_codes"][hai_type]
    cm = cfg["icd10_us_billable"]
    who = cfg["icd10_jp_who"]
    snomed = cfg["snomed"]
    assert lookup("icd-10-cm", cm, "en"), f"icd-10-cm/{cm}/en empty"
    assert lookup("icd-10-cm", cm, "ja"), f"icd-10-cm/{cm}/ja empty"
    assert lookup("icd-10", who, "en"), f"icd-10/{who}/en empty"
    assert lookup("icd-10", who, "ja"), f"icd-10/{who}/ja empty"
    assert lookup("snomed-ct", snomed, "en"), f"snomed-ct/{snomed}/en empty"
    assert lookup("snomed-ct", snomed, "ja"), f"snomed-ct/{snomed}/ja empty"


@pytest.mark.parametrize("hai_type", ["clabsi", "cauti", "vap"])
def test_hai_organism_codes_resolve(hai_type):
    organisms = load_hai_organisms()["hai_organisms"][hai_type]
    for entry in organisms:
        snomed = entry["snomed"]
        en = lookup("snomed-ct", snomed, "en")
        assert en, f"snomed-ct/{snomed}/en empty"
        assert en != snomed, f"snomed-ct/{snomed}/en is the bare code"


@pytest.mark.parametrize("hai_type", ["clabsi", "cauti", "vap"])
def test_hai_specimen_codes_resolve(hai_type):
    spec_cfg = load_hai_specimens()["hai_specimens"][hai_type]
    spec_snomed = spec_cfg["specimen_snomed"]
    test_loinc = spec_cfg["test_loinc"]
    assert lookup("snomed-ct", spec_snomed, "en"), f"snomed-ct/{spec_snomed}/en empty"
    assert lookup("loinc", test_loinc, "en"), f"loinc/{test_loinc}/en empty"
