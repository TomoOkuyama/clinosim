"""Unit tests for body_sites YAML loader/validator."""

from __future__ import annotations

from clinosim.modules.imaging.engine import load_body_sites


def test_body_sites_loads_chest_and_head():
    bs = load_body_sites()
    assert "chest" in bs
    assert "head" in bs


def test_chest_has_cr_and_ct_procedure_codes():
    bs = load_body_sites()
    chest = bs["chest"]
    assert chest["snomed"] == "51185008"
    assert chest["display_ja"] == "胸部"
    assert "CR_PA_Lateral" in chest["procedure_codes"]
    assert "CT_non_contrast" in chest["procedure_codes"]


def test_head_has_ct_non_contrast_procedure_code():
    bs = load_body_sites()
    head = bs["head"]
    assert head["snomed"] == "69536005"
    assert "CT_non_contrast" in head["procedure_codes"]
    code = head["procedure_codes"]["CT_non_contrast"]
    assert code["loinc"] == "30799-1"
    assert code["cpt"] == "70450"
