"""Issue #3106: JP dose and timing text reads as Japanese chart notation.

The JP dose-text translator (``_localize_dosage_terms``) substitutes the
``med_terms.yaml`` entries longest-first, so a multi-word phrase entry
(``nasal spray``) wins over its words. English output is unchanged.
"""

from __future__ import annotations

import glob
import re

import pytest
import yaml

from clinosim.locale.free_text import _localize_dosage_terms

pytestmark = pytest.mark.unit


def test_a_one_time_dose_reads_1kai_in_jp() -> None:
    out = _localize_dosage_terms("0.5mg IM once", "ja")
    assert out == "0.5mg 筋注 1回"
    assert "一度" not in _localize_dosage_terms("once", "ja")


@pytest.mark.parametrize(
    ("en", "ja"),
    [
        ("Calcitonin nasal spray", "Calcitonin 点鼻"),
        ("5ug/kg/min IV drip", "5ug/kg/分 点滴静注"),
        ("100mcg Q4-6H PRN", "100mcg 4-6時間毎 頓用"),
        ("q6-8h", "6-8時間毎"),
        ("Controlled O2 target SpO2 88-92%", "調節酸素投与 目標 SpO2 88-92%"),
        ("avoid hyperoxia in CO2 retainers", "CO2 貯留患者では高酸素を避ける"),
        ("once hemodynamically stable", "血行動態安定後"),
        ("NS or LR wide open", "NS または LR 全開"),
        ("162-325mg loading, then 100mg PO daily", "162-325mg 負荷投与後 100mg 経口 1日1回"),
    ],
)
def test_phrase_entries_win_over_word_entries(en: str, ja: str) -> None:
    assert _localize_dosage_terms(en, "ja") == ja


def _dose_strings() -> list[str]:
    out: set[str] = set()

    def walk(x: object) -> None:
        if isinstance(x, dict):
            for k, v in x.items():
                if k in ("dose", "detail", "frequency") and isinstance(v, str):
                    out.add(v)
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)

    for path in glob.glob("clinosim/modules/disease/reference_data/*.yaml") + glob.glob(
        "clinosim/locale/shared/chronic_medications.yaml"
    ):
        walk(yaml.safe_load(open(path, encoding="utf-8")))
    return sorted(out)


def test_english_dose_text_is_unchanged_for_protocol_and_locale_dose_strings() -> None:
    """The entries carry no English slot: English text passes through."""
    strings = _dose_strings()
    assert len(strings) > 100
    changed = [s for s in strings if _localize_dosage_terms(s, "en") != s]
    # Only protocol slugs with an `en` slot (``iv_fluid: ...``) are rewritten in English.
    assert all("_" in s for s in changed), changed
    assert not [s for s in strings if re.search(r"[぀-ヿ一-鿿]", _localize_dosage_terms(s, "en"))]


def test_an_iv_drip_reads_tenteki_jochu_once() -> None:
    from clinosim.modules.output.fhir_r4.lib.dosage import build_dosage_instruction

    order = {"dose_quantity": 5, "dose_unit": "ug/kg/min", "route": "IV", "frequency": "DRIP"}
    ja = build_dosage_instruction(order, "JP")
    en = build_dosage_instruction(order, "US")
    assert ja is not None and "点滴静注" in ja["text"] and "静注 点滴静注" not in ja["text"]
    assert en is not None and "IV" in en["text"]
