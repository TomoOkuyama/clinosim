"""Characterization tests for JP medication-term localization (DUP-2).

`_localize_dosage_terms` translates dose/route/frequency abbreviations and
category prefixes to Japanese. The translation tables were moved from inline
Python dicts to locale/shared/med_terms_ja.yaml; these tests pin the observed
output so the move is proven behavior-preserving (golden-safe), and guard the
order-sensitive substitution semantics.
"""

import pytest

from clinosim.modules.output.fhir_r4_adapter import (
    _load_med_terms_ja,
    _localize_dosage_terms,
)

# (input, expected output) — captured from the pre-refactor implementation.
CASES = [
    ("PRN PO", "頓用 経口"),
    ("bid", "1日2回"),
    ("IV bolus", "静注 ボーラス"),
    ("DVT prophylaxis", "DVT予防"),
    ("antipyretic PRN q6h", "解熱剤 頓用 6時間毎"),
    ("Nebulized bronchodilator", "ネブライザー 気管支拡張薬"),
    ("hold if hemodynamically unstable", "保留 場合 血行動態 unstable"),
    ("Pneumatic compression devices", "間欠的空気圧迫装置"),
    ("titrate to MAP", "調節 まで MAP（平均動脈圧）"),
]


@pytest.mark.unit
@pytest.mark.parametrize("text,expected", CASES)
def test_localize_dosage_terms_pinned(text, expected):
    assert _localize_dosage_terms(text) == expected


@pytest.mark.unit
def test_med_terms_tables_loaded():
    tables = _load_med_terms_ja()
    # Representative entries from each table.
    assert tables["categories"]["antipyretic"] == "解熱剤"
    assert tables["terms"]["PRN"] == "頓用"
    assert tables["terms"]["q6h"] == "6時間毎"
    # Sizes match the original inline dicts.
    assert len(tables["categories"]) == 16
    assert len(tables["terms"]) == 148
