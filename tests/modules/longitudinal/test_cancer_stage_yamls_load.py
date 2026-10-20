"""Phase 4c — AJCC/BCLC Markov stage ladders for 6 cancer families load.

Six yamls under clinosim/locale/shared/longitudinal/stage/ (one per
C-code family). The Phase 2 Markov pattern + loader are reused unchanged.
"""

from __future__ import annotations

from clinosim.modules.longitudinal.loader import load_attribute_specs

AJCC_STATES = ["AJCC I", "AJCC II", "AJCC III", "AJCC IV"]


def test_gastric_cancer_stage_yaml_loads():
    load_attribute_specs.cache_clear()
    specs = load_attribute_specs()
    assert "gastric_cancer_stage_c16" in specs
    spec = specs["gastric_cancer_stage_c16"]
    assert spec.pattern == "markov"
    assert spec.clinical_scope.requires_chronic_codes == ["C16"]
    body = spec.body
    assert body.icd_base == "C16"
    assert body.states == AJCC_STATES
    assert body.transitions["AJCC IV"] == {}
    assert body.transitions["AJCC I"]["AJCC II"] == 0.15
    assert body.transitions["AJCC II"]["AJCC III"] == 0.10
    assert body.transitions["AJCC III"]["AJCC IV"] == 0.08


def test_colon_cancer_stage_yaml_loads():
    load_attribute_specs.cache_clear()
    specs = load_attribute_specs()
    assert "colon_cancer_stage_c18" in specs
    spec = specs["colon_cancer_stage_c18"]
    assert spec.pattern == "markov"
    assert spec.clinical_scope.requires_chronic_codes == ["C18"]
    body = spec.body
    assert body.icd_base == "C18"
    assert body.states == AJCC_STATES
    assert body.transitions["AJCC IV"] == {}
    assert body.transitions["AJCC I"]["AJCC II"] == 0.12
    assert body.transitions["AJCC II"]["AJCC III"] == 0.08
    assert body.transitions["AJCC III"]["AJCC IV"] == 0.06


BCLC_STATES = ["BCLC 0", "BCLC A", "BCLC B", "BCLC C", "BCLC D"]


def test_liver_cancer_stage_yaml_loads():
    load_attribute_specs.cache_clear()
    specs = load_attribute_specs()
    assert "liver_cancer_stage_c22" in specs
    spec = specs["liver_cancer_stage_c22"]
    assert spec.pattern == "markov"
    assert spec.clinical_scope.requires_chronic_codes == ["C22"]
    body = spec.body
    assert body.icd_base == "C22"
    assert body.states == BCLC_STATES
    assert body.transitions["BCLC D"] == {}
    assert body.transitions["BCLC 0"]["BCLC A"] == 0.20
    assert body.transitions["BCLC A"]["BCLC B"] == 0.18
    assert body.transitions["BCLC B"]["BCLC C"] == 0.15
    assert body.transitions["BCLC C"]["BCLC D"] == 0.20


def test_lung_cancer_stage_yaml_loads():
    load_attribute_specs.cache_clear()
    specs = load_attribute_specs()
    assert "lung_cancer_stage_c34" in specs
    spec = specs["lung_cancer_stage_c34"]
    assert spec.clinical_scope.requires_chronic_codes == ["C34"]
    body = spec.body
    assert body.icd_base == "C34"
    assert body.states == AJCC_STATES
    assert body.transitions["AJCC IV"] == {}
    assert body.transitions["AJCC I"]["AJCC II"] == 0.18
    assert body.transitions["AJCC II"]["AJCC III"] == 0.12
    assert body.transitions["AJCC III"]["AJCC IV"] == 0.10


def test_breast_cancer_stage_yaml_loads():
    load_attribute_specs.cache_clear()
    specs = load_attribute_specs()
    assert "breast_cancer_stage_c50" in specs
    spec = specs["breast_cancer_stage_c50"]
    assert spec.clinical_scope.requires_chronic_codes == ["C50"]
    body = spec.body
    assert body.icd_base == "C50"
    assert body.states == AJCC_STATES
    assert body.transitions["AJCC IV"] == {}
    assert body.transitions["AJCC I"]["AJCC II"] == 0.08
    assert body.transitions["AJCC II"]["AJCC III"] == 0.06
    assert body.transitions["AJCC III"]["AJCC IV"] == 0.05


def test_prostate_cancer_stage_yaml_loads():
    load_attribute_specs.cache_clear()
    specs = load_attribute_specs()
    assert "prostate_cancer_stage_c61" in specs
    spec = specs["prostate_cancer_stage_c61"]
    assert spec.clinical_scope.requires_chronic_codes == ["C61"]
    body = spec.body
    assert body.icd_base == "C61"
    assert body.states == AJCC_STATES
    assert body.transitions["AJCC IV"] == {}
    assert body.transitions["AJCC I"]["AJCC II"] == 0.05
    assert body.transitions["AJCC II"]["AJCC III"] == 0.04
    assert body.transitions["AJCC III"]["AJCC IV"] == 0.03


def test_breast_subcode_matches_c50_prefix():
    """Review Focus #1: C50.1 (upper-outer quadrant) must engage the
    breast attribute via requires_chronic_codes prefix match."""
    from datetime import date

    import numpy as np

    from clinosim.modules.longitudinal import engine as le
    from clinosim.types.population import PersonRecord

    load_attribute_specs.cache_clear()
    p = PersonRecord(
        person_id="PX",
        household_id="HX",
        age=55,
        sex="F",
        date_of_birth=date(1970, 1, 1),
        chronic_conditions=["C50.1"],
    )
    snap = le.initial_snapshot(p, 2024, np.random.default_rng(0))
    assert "C50" in snap.chronic_stages
    assert snap.chronic_stages["C50"] in {"AJCC I", "AJCC II", "AJCC III", "AJCC IV"}
