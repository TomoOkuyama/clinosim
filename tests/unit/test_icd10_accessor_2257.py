"""One ICD-10 accessor for system, display, short name and MEDIS crosswalk (Issue #2257)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from clinosim.codes import get_system_uri
from clinosim.codes.icd10 import condition_short_name, icd10_display, icd10_system, medis_disease_keyno

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[2]


def test_icd10_system_per_country() -> None:
    assert icd10_system("US") == "icd-10-cm"
    assert icd10_system("jp") == "icd-10-mhlw"


def test_icd10_display_per_country_and_language() -> None:
    assert icd10_display("I10", "US", "en") == "Essential (primary) hypertension"
    assert icd10_display("I10", "JP", "ja") == "本態性（原発性＜一次性＞）高血圧（症）"  # MHLW 2013 name
    assert icd10_display("Z99.99X", "US", "en") is None
    assert icd10_display("", "US", "en") is None


def test_condition_short_name_uses_the_category() -> None:
    assert condition_short_name("J44.1", "en") == "COPD"
    assert condition_short_name("I10", "ja") == "高血圧"
    assert condition_short_name("Q99.9", "en") is None


def test_medis_crosswalk_and_uri_are_registered() -> None:
    assert medis_disease_keyno("I50.0") == ("20084004", "うっ血性心不全")
    assert medis_disease_keyno("I10") is None
    assert get_system_uri("medis-disease-keyno") == "http://medis.or.jp/CodeSystem/master-disease-keyNumber"


def test_retired_icd_display_sources_are_gone() -> None:
    assert not (_ROOT / "clinosim/codes/data/icd10-condition-display.yaml").exists()
    for path in (_ROOT / "clinosim/modules/encounter/reference_data").glob("*.yaml"):
        assert "icd10_display:" not in path.read_text(encoding="utf-8"), path.name


def test_no_country_to_icd_system_ternary_outside_codes() -> None:
    pattern = re.compile(r"\"icd-10(?:-mhlw)?\" if [^\n]*else \"icd-10-cm\"")
    offenders = [
        str(p.relative_to(_ROOT))
        for p in (_ROOT / "clinosim").rglob("*.py")
        if "clinosim/codes/" not in str(p) and pattern.search(p.read_text(encoding="utf-8"))
    ]
    assert not offenders, offenders
