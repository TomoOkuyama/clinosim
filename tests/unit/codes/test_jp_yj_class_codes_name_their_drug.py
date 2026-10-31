"""Every JP YJ code in the drug catalog names the drug it is mapped from
(Issues #2134, #2347).

Wrong codes slipped through before (e.g. Sertraline → 1179044, an olanzapine
class; Amlodipine → a valsartan/amlodipine combination product). This checks
each catalog YJ code against the MHLW YJ master snapshot
(``codes/authoritative/yj_mhlw_snapshot.json``): its ingredient or product name
must carry the drug's Japanese generic name or one of its brand names.
"""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

import pytest

from clinosim.codes.drugs import all_drug_ids, jp_drug_code, resolve_drug

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[3]
_SNAPSHOT = _ROOT / "clinosim/codes/authoritative/yj_mhlw_snapshot.json"

# Products listed in the master only under a brand name.
_BRANDS: dict[str, tuple[str, ...]] = {
    "Enoxaparin": ("クレキサン",),
    "Apixaban": ("エリキュース",),
    "Methylprednisolone": ("メドロール",),
    "Diphenhydramine": ("レスタミン",),
    "Ipratropium": ("アトロベント",),
    "Edoxaban": ("リクシアナ",),
    "Metronidazole": ("フラジール", "アスゾール"),
    "Aztreonam": ("アザクタム",),
    "Bisoprolol": ("ビソノテープ",),
    "Clindamycin": ("ダラシン",),
    "Denosumab": ("ランマーク", "プラリア"),
    "Idarucizumab": ("プリズバインド",),
    "Insulin aspart": ("ノボラピッド",),
    "Insulin glargine": ("ランタス",),
    "Insulin lispro": ("ヒューマログ",),
    "Moxifloxacin": ("アベロックス",),
    "Patiromer": ("ビルタサ",),
    "Peramivir": ("ラピアクタ",),
    "Rifaximin": ("リフキシマ",),
    "Ticagrelor": ("ブリリンタ",),
    "Venlafaxine": ("イフェクサー",),
    "Sertraline": ("ジェイゾロフト",),
    "Escitalopram": ("レクサプロ",),
    "Paroxetine": ("パキシル",),
    "Fluvoxamine": ("デプロメール", "ルボックス"),
    "Tamsulosin": ("ハルナール",),
    "Bupivacaine": ("マーカイン",),
    "Irinotecan": ("カンプト", "トポテシン"),
    "Nab-paclitaxel": ("アブラキサン",),
    "Ampicillin": ("ビクシリン",),
    "Norepinephrine": ("ノルアドレナリン",),
    "4-Factor PCC (Kcentra)": ("ケイセントラ",),
    "Prothrombin Complex Concentrate (4F-PCC)": ("ケイセントラ",),
    "Ferrous_sulfate": ("フェログラデュメット",),
    # Issue #2136 additions.
    "Acamprosate": ("レグテクト",),
    "Cyclopentolate": ("サイプレジン",),
    "Disulfiram": ("ノックビン",),
    "Empagliflozin": ("ジャディアンス",),
    "Liraglutide": ("ビクトーザ",),
    "Nalmefene": ("セリンクロ",),
    "Naphazoline": ("プリビナ",),
    "Semaglutide": ("オゼンピック",),
    # Issue #2155 additions.
    "Hydroxyzine": ("アタラックス",),
    "Naproxen": ("ナイキサン",),
    # Issue #2347: Japanese names that differ from the master's ingredient name.
    "Epinephrine": ("アドレナリン",),
    "Leucovorin": ("ホリナート",),
    "Insulin, Regular, Human": ("インスリンヒト",),
    "Sliding scale insulin": ("インスリンヒト",),
    "Vitamin K": ("フィトナジオン",),
}


def _norm(text: str) -> str:
    return re.sub(r"[（）()・ー\s　「」]", "", unicodedata.normalize("NFKC", text))


def _catalog_codes() -> list[tuple[str, str, str]]:
    return sorted(
        (rec.names["en"], rec.names["ja"], code)
        for rec in (resolve_drug(d) for d in all_drug_ids())
        for code in rec.yj_by_route.values()
    )


def test_catalog_yj_codes_name_their_drug() -> None:
    master = json.loads(_SNAPSHOT.read_text(encoding="utf-8"))["codes"]
    brands = {k.lower().replace("_", " "): v for k, v in _BRANDS.items()}
    wrong = []
    for en, ja, code in _catalog_codes():
        entry = master[code]
        text = _norm(entry["ingredient"]) + _norm(entry["product"])
        keys = [k for k in (_norm(ja)[:4], *(_norm(b) for b in brands.get(en.lower(), ()))) if k]
        if not any(k in text for k in keys):
            wrong.append((en, code, ja, entry["product"]))
    assert not wrong, "YJ codes naming another drug: " + "; ".join(f"{e} {c} ({j}) → {p}" for e, c, j, p in wrong)


def test_ketorolac_has_no_jp_code() -> None:
    # Not marketed in Japan; the former 1149029 is a zaltoprofen class.
    assert jp_drug_code("Ketorolac", "IV") is None and jp_drug_code("Ketorolac", "PO") is None


def test_lowercase_drug_ids_resolve_to_jp_codes() -> None:
    # Chronic medications carry lowercase drug ids ("sertraline").
    from clinosim.modules.output.fhir_r4.medications.medications import _resolve_medication_concept

    concept, _ = _resolve_medication_concept("sertraline", order_code="", country="JP", route="PO")
    assert concept["coding"][0]["code"].startswith("1179046")
    concept, _ = _resolve_medication_concept("mirtazapine 15mg", order_code="", country="JP", route="PO")
    assert concept["coding"][0]["code"].startswith("1179051")
    concept, _ = _resolve_medication_concept("Lactulose 30mL", order_code="", country="JP", route="PO")
    assert concept["coding"][0]["code"].startswith("3999001")
