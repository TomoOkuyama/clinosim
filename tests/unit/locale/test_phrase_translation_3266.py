"""Issue #3266: JP order annotations read as Japanese phrases, not word salad.

The free-text translator substitutes ``med_terms.yaml`` entries longest-first,
so an annotation phrase ("avoid hypotonic fluids") is translated as a whole.
Single English words that cannot be translated out of context ("avoid",
"under", "may", "not", ...) have no entry, so they never turn an annotation
into a row of unrelated Japanese words. An ED patient sent home is 帰宅.
"""

from __future__ import annotations

import glob
import re

import pytest
import yaml

from clinosim.locale.free_text import localize_drug_name, localize_free_text, localize_procedure_name
from clinosim.locale.i18n import t
from clinosim.locale.loader import load_med_terms

pytestmark = pytest.mark.unit

_JW = r"[぀-ヿ一-鿿々ー]+"
_PAREN = re.compile(r"[(（]([^()（）]*)[)）]")
_SALAD = re.compile(rf"(?:^|\s){_JW}(?:\s+{_JW}){{2,}}(?:\s|$)")


def _salad(ja: str) -> bool:
    """Three or more space-separated Japanese words inside one pair of parentheses."""
    return any(_SALAD.search(m.group(1)) for m in _PAREN.finditer(ja))


@pytest.mark.parametrize(
    ("en", "ja"),
    [
        ("IV_fluid: NS 80 mL/h (avoid hypotonic fluids)", "輸液: 生理食塩液 80 mL/h (低張液は避ける)"),
        (
            "IV_fluid: NS 80 mL/h (cautious — RV may not tolerate volume)",
            "輸液: 生理食塩液 80 mL/h (右室負荷に注意し慎重に)",
        ),
        (
            "IV_fluid: NS 80 mL/h — avoid hypotonic fluids (cerebral edema risk)",
            "輸液: 生理食塩液 80 mL/h — 低張液は避ける (脳浮腫のリスク)",
        ),
        ("Alteplase 0.6mg/kg IV over 2h (max 40mg JP dose)", "アルテプラーゼ 0.6mg/kg 2時間かけて静注 (最大 40mg)"),
        ("Heparin Increase infusion rate", "ヘパリン 投与速度を増量"),
        (
            "Salbutamol 2.5mg nebulizer q4h (q1h PRN acute)",
            "サルブタモール 2.5mg ネブライザー 4時間毎 (急性期は1時間毎に頓用)",
        ),
        (
            "antipyretic: Acetaminophen 500mg PO q6h PRN temp >= 38.5",
            "解熱剤: アセトアミノフェン 500mg 経口 6時間毎 頓用（38.5℃以上の発熱時）",
        ),
        (
            "K_replacement: KCl 20-40 mEq/L in IV fluids, target K 4.0-5.0",
            "カリウム補充: 塩化カリウム 20-40 mEq/L を輸液に混注, 目標 K 4.0-5.0",
        ),
    ],
)
def test_order_annotations_read_as_japanese_phrases(en: str, ja: str) -> None:
    assert localize_drug_name(en, "ja") == ja


def test_vertebroplasty_under_fluoroscopy_reads_toushika() -> None:
    assert localize_procedure_name("Percutaneous vertebroplasty under fluoroscopy", "ja") == "透視下経皮的椎体形成術"
    assert localize_free_text("Vertebroplasty: Percutaneous vertebroplasty under fluoroscopy", "ja").endswith(
        "透視下経皮的椎体形成術"
    )


@pytest.mark.parametrize("word", ["avoid", "under", "may", "not", "tolerate", "volume", "JP"])
def test_out_of_context_single_words_have_no_entry(word: str) -> None:
    assert word not in load_med_terms()["terms"]


def _order_strings() -> list[str]:
    """Every supportive-order detail (``type: detail``) and medication dose of
    the disease and encounter protocols, as the order string carries it."""
    out: set[str] = set()

    def walk(x: object) -> None:
        if isinstance(x, dict):
            kind = x.get("type")
            for k, v in x.items():
                if isinstance(v, str) and k == "detail":
                    out.add(f"{kind}: {v}" if isinstance(kind, str) else v)
                elif isinstance(v, str) and k in ("dose", "frequency"):
                    out.add(v)
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)

    for path in sorted(
        glob.glob("clinosim/modules/disease/reference_data/*.yaml")
        + glob.glob("clinosim/modules/encounter/reference_data/*.yaml")
    ):
        with open(path, encoding="utf-8") as fh:
            walk(yaml.safe_load(fh))
    return sorted(out)


def test_no_protocol_order_annotation_renders_as_word_salad_in_ja() -> None:
    strings = _order_strings()
    assert len(strings) > 200
    bad = [(s, ja) for s in strings if _salad(ja := localize_drug_name(s, "ja"))]
    assert not bad, bad


@pytest.mark.parametrize(
    ("lang", "start"),
    [("ja", "帰宅（JTAS レベル 4、"), ("en", "Discharged home (ESI level 4, ")],
)
def test_ed_home_disposition_is_kitaku_in_ja(lang: str, start: str) -> None:
    text = t("fallback.ed_disposition_home", lang).format(level=4, reason="x")
    assert text.startswith(start)
    assert "退院" not in text
