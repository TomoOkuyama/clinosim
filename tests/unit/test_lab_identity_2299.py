"""Lab identity resolves through canonical names at every boundary (Issue #2299)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from clinosim.benchmarks.aki import _creatinine_delta
from clinosim.modules.observation.engine import LAB_UNITS, canonical_lab_name, get_lab_unit
from clinosim.modules.output.hospital_course_extractor import _normalize_lab_name, _unit_for

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(("alias", "canonical"), [("aPTT", "APTT"), ("T_Bilirubin", "T_Bil"), ("Magnesium", "Mg")])
def test_alias_spellings_resolve(alias: str, canonical: str) -> None:
    assert canonical_lab_name(alias) == canonical


def test_hba1c_is_not_haemoglobin() -> None:
    assert _normalize_lab_name("HbA1c") == "HbA1c"
    assert _normalize_lab_name("Hb") == "Hb"


def test_units_come_from_the_shared_table() -> None:
    assert get_lab_unit("aPTT") == LAB_UNITS["APTT"]
    for name in ("CRP", "WBC", "Creatinine", "Lactate", "Hb", "Plt"):
        assert _unit_for(name, "en") == LAB_UNITS[name]


def test_us_code_mapping_keys_are_canonical_or_unaliased() -> None:
    us = yaml.safe_load((_ROOT / "clinosim/locale/us/code_mapping_lab.yaml").read_text(encoding="utf-8"))
    aliased = [k for k in us if canonical_lab_name(k) != k]
    assert not aliased, aliased


def test_aki_benchmark_reads_canonical_creatinine() -> None:
    rec = {"lab_results": [{"lab_name": "Creatinine", "value": 1.0}, {"lab_name": "Creatinine", "value": 1.6}]}
    assert _creatinine_delta(rec) == pytest.approx(0.6)
