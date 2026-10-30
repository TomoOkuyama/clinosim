"""Radiation-therapy procedures carry each country's own code (Issue #2200)."""

from __future__ import annotations

import pytest

from clinosim.codes import lookup
from clinosim.locale.loader import load_chronic_followup
from clinosim.simulator.outpatient import radiation_therapy_code

pytestmark = pytest.mark.unit


def test_us_uses_cpt_external_beam_delivery() -> None:
    assert radiation_therapy_code("US") == "77412"
    assert lookup("cpt", "77412", "en") != "77412"  # registered in cpt.yaml


def test_jp_uses_m001_external_beam() -> None:
    assert radiation_therapy_code("JP") == "M001"
    assert lookup("k-codes", "M001", "ja").startswith("体外照射")


def test_k_code_displays_match_the_fee_schedule() -> None:
    # 診療報酬点数表 第7部: M001-2 = ガンマナイフ, M001-3 = 直線加速器による放射線治療.
    assert "ガンマナイフ" in lookup("k-codes", "M001-2", "ja")
    assert "直線加速器" in lookup("k-codes", "M001-3", "ja")


def test_config_lives_in_yaml() -> None:
    cfg = load_chronic_followup()["_radiation_therapy"]
    assert {"jp_code", "us_code", "visit_probability"} <= set(cfg)
