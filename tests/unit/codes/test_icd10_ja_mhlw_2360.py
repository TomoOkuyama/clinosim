"""JP ICD-10 Japanese displays come from the MHLW table only (Issue #2360)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from clinosim.codes.icd10 import condition_label, condition_short_name, icd10_display
from clinosim.locale.loader import load_code_mapping

pytestmark = pytest.mark.unit

_DATA = Path(__file__).resolve().parents[3] / "clinosim" / "codes" / "data"


def _codes(name: str) -> dict[str, dict[str, str]]:
    return yaml.safe_load((_DATA / name).read_text(encoding="utf-8"))["codes"]


def _mapping_targets() -> set[str]:
    out: set[str] = set()
    for value in load_code_mapping("diagnosis", "JP").values():
        if isinstance(value, dict):
            out.add(str(value.get("default")))
            out.update(str(v) for v in (value.get("by_sex") or {}).values())
        else:
            out.add(str(value))
    return out


def test_every_jp_mapping_target_has_its_own_japanese_name() -> None:
    who = _codes("icd-10.yaml")
    missing = sorted(t for t in _mapping_targets() if t not in who or not who[t].get("ja"))
    assert not missing


def test_jp_display_is_the_mhlw_name_not_the_cm_text() -> None:
    who = _codes("icd-10.yaml")
    for code in sorted(_mapping_targets()):
        assert icd10_display(code, "JP", "ja") == who[code]["ja"], code


def test_cm_table_carries_no_japanese_for_a_code_shared_with_who() -> None:
    who, cm = _codes("icd-10.yaml"), _codes("icd-10-cm.yaml")
    assert not sorted(c for c in cm if c in who and "ja" in cm[c])


def test_cm_only_crushing_injury_maps_to_a_who_code() -> None:
    assert load_code_mapping("diagnosis", "JP")["S67.2"] == "S67.8"
    assert "S67.2" not in _codes("icd-10.yaml")


def test_condition_label_prefers_the_short_name() -> None:
    assert condition_short_name("I10", "ja")
    assert condition_label("I10", "JP", "ja") == condition_short_name("I10", "ja")
    # No short name: the official display.
    assert condition_label("S67.8", "JP", "ja") == "手首及び手のその他及び部位不明の挫滅損傷"
    assert condition_label("ZZZ.9", "JP", "ja") is None
