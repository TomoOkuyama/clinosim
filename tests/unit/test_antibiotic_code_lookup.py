"""Unit tests for Vancomycin RxNorm + YJ code registration."""

import pytest

from clinosim.codes import lookup
from clinosim.locale.loader import load_code_mapping


@pytest.mark.unit
def test_vancomycin_rxnorm_lookup_en():
    us_map = load_code_mapping("drug", "US")
    cui = us_map.get("Vancomycin", "")
    assert cui, "Vancomycin missing from code_mapping_drug/us.yaml"
    en = lookup("rxnorm", cui, "en")
    assert en and en != cui
    assert "vancomycin" in en.lower()


@pytest.mark.unit
def test_vancomycin_yj_lookup_ja():
    jp_map = load_code_mapping("drug", "JP")
    yj = jp_map.get("Vancomycin", "")
    assert yj, "Vancomycin missing from code_mapping_drug/jp.yaml"
    ja = lookup("yj", yj, "ja")
    assert ja and ja != yj
    assert "バンコマイシン" in ja


@pytest.mark.unit
def test_ceftriaxone_pip_tazo_already_mapped_both_locales():
    us_map = load_code_mapping("drug", "US")
    jp_map = load_code_mapping("drug", "JP")
    for drug in ("Ceftriaxone", "Piperacillin/Tazobactam"):
        assert us_map.get(drug), f"{drug} missing from US"
        assert jp_map.get(drug), f"{drug} missing from JP"
