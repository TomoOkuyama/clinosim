"""Issue #332 sibling — R53.1 は WHO ICD-10 に存在しない (CM 拡張)。

v9 (seed=500 p=5000 master cbfacc6ebf) validation で 78 件 unknown-code
error:

    Unknown code 'R53.1' in the CodeSystem
    'http://hl7.org/fhir/sid/icd-10' version '2019-covid-expanded'

`simulator/inpatient.py:2282/2318` の discharge_code / admission_diagnosis_code
が非 fever event で R53.1 (ICD-10-CM "Weakness") を emit。JP path は WHO
ICD-10 (`sid/icd-10`) へ send するが、WHO ICD-10 の R53 は「Malaise and
fatigue」の 3-character category code のみ (no subcodes)、R53.1 は無い。

Fix: `locale/jp/code_mapping_diagnosis.yaml` に R53.1 → R53 mapping 追加。
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.unit


_REPO_ROOT = Path(__file__).resolve().parents[2]
_JP_MAPPING = _REPO_ROOT / "clinosim" / "locale" / "jp" / "code_mapping_diagnosis.yaml"
_ICD10_WHO = _REPO_ROOT / "clinosim" / "codes" / "data" / "icd-10.yaml"


def _load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text()) or {}


def test_jp_mapping_folds_r53_1_to_who_r53() -> None:
    mapping = _load_yaml(_JP_MAPPING)
    assert mapping.get("R53.1") == "R53", (
        "Issue #332: R53.1 (Weakness) は ICD-10-CM 拡張、WHO ICD-10 は "
        "R53 (Malaise and fatigue) のみ。JP mapping で R53.1 → R53 fold "
        "が必須(未 fold だと sid/icd-10 に R53.1 emit されて validator "
        "が unknown-code error)。"
    )


def test_who_icd10_yaml_has_r53_parent() -> None:
    icd10 = _load_yaml(_ICD10_WHO)
    codes = icd10.get("codes", {})
    assert "R53" in codes, (
        "Issue #332: R53.1 → R53 mapping target R53 must exist in "
        "codes/data/icd-10.yaml with authoritative WHO display."
    )
    assert codes["R53"].get("en"), "R53 must carry en display"
