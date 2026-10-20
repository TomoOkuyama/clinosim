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
