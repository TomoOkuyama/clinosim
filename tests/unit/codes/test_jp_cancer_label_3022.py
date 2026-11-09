"""JP cancer Conditions name the disease (Issue #3022).

The MHLW 基本分類表 (kihon2013) names a C-code subcategory only by its site
("C16.9 胃，部位不明"); the category title carries 悪性新生物. The coding
display stays the MHLW name verbatim, and the label used in
``Condition.code.text`` and prose is the clinical name of the cancer.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from clinosim.codes.icd10 import condition_label, icd10_display

pytestmark = pytest.mark.unit

_DATA = Path(__file__).resolve().parents[3] / "clinosim" / "codes" / "data"
_MALIGNANT = ("悪性", "癌", "肉腫", "白血病", "リンパ腫", "骨髄腫")


def _c_codes() -> list[str]:
    codes = yaml.safe_load((_DATA / "icd-10.yaml").read_text(encoding="utf-8"))["codes"]
    return sorted(c for c in codes if c.startswith("C"))


@pytest.mark.parametrize("code", _c_codes())
def test_every_jp_cancer_label_names_a_malignancy(code: str) -> None:
    label = condition_label(code, "JP", "ja") or ""
    assert any(word in label for word in _MALIGNANT), (code, label)


def test_the_coding_display_stays_the_mhlw_name() -> None:
    assert icd10_display("C16.9", "JP", "ja") == "胃，部位不明"
    assert condition_label("C16.9", "JP", "ja") == "胃癌"


def test_the_english_label_names_the_cancer_too() -> None:
    assert condition_label("C16.9", "US", "en") == "Gastric cancer"
