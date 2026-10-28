"""Every JP 7-digit YJ class code names the drug it is mapped from (Issue #2134).

The tx fragment snapshot (``yj_tx_fragment.json``) covers only a handful of
codes, so wrong class codes slipped through (e.g. Sertraline → 1179044, an
olanzapine class). This checks each 7-digit mapping in
``locale/jp/code_mapping_drug.yaml`` against the bundled YJ product master:
some product under the class must carry the drug's Japanese generic name or
one of its brand names.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[3]
_MASTER = _ROOT / "clinosim/codes/authoritative/JP_MedicationCodeYJ_CS_full.json"
_MAPPING = _ROOT / "clinosim/locale/jp/code_mapping_drug.yaml"
_DRUGS = _ROOT / "clinosim/codes/data/drugs.yaml"
_HOT7 = _ROOT / "clinosim/codes/data/hot7.yaml"

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
}


def _norm(text: str) -> str:
    return re.sub(r"[（）()・ー\s　「」]", "", text)


def _ja_names() -> dict[str, str]:
    names: dict[str, str] = {}
    drugs = yaml.safe_load(_DRUGS.read_text(encoding="utf-8"))
    for entry in (drugs.get("drugs", drugs) or {}).values():
        if isinstance(entry, dict) and "names" in entry:
            names[str(entry["names"].get("en", "")).lower()] = str(entry["names"].get("ja", ""))
    return names


def _mapped_class_codes() -> list[tuple[str, str]]:
    mapping = yaml.safe_load(_MAPPING.read_text(encoding="utf-8"))
    return sorted(
        (str(name), code) for name, code in mapping.items() if isinstance(code, str) and re.fullmatch(r"\d{7}", code)
    )


def test_class_codes_name_their_drug() -> None:
    master = json.loads(_MASTER.read_text(encoding="utf-8"))
    products: dict[str, list[str]] = defaultdict(list)
    for concept in master.get("concept", master):
        products[concept["code"][:7]].append(_norm(concept.get("display") or ""))
    hot7 = yaml.safe_load(_HOT7.read_text(encoding="utf-8"))
    hot7 = hot7.get("codes", hot7)
    ja = _ja_names()

    wrong = []
    for name, code in _mapped_class_codes():
        displays = products.get(code)
        if not displays:
            continue  # code outside the master (checked elsewhere)
        generic = ja.get(name.lower()) or str((hot7.get(code) or {}).get("ja", ""))
        keys = [k for k in (_norm(generic)[:4], *(_norm(b) for b in _BRANDS.get(name, ()))) if k]
        if not keys:
            continue  # no Japanese name registered to compare against
        if not any(k in d for d in displays for k in keys):
            wrong.append((name, code, generic, displays[0]))
    assert not wrong, "YJ class codes naming another drug: " + "; ".join(f"{n} {c} ({g}) → {d}" for n, c, g, d in wrong)


def test_ketorolac_has_no_jp_code() -> None:
    # Not marketed in Japan; the former 1149029 is a zaltoprofen class.
    mapping = yaml.safe_load(_MAPPING.read_text(encoding="utf-8"))
    assert "Ketorolac" not in mapping


def test_lowercase_drug_ids_resolve_to_jp_codes() -> None:
    # Chronic medications carry lowercase drug ids ("sertraline"); the JP
    # mapping keys are capitalised, so exact-case lookup fell to NOCODED.
    from clinosim.modules.output.fhir_r4.medications.medications import _resolve_medication_concept

    concept, _ = _resolve_medication_concept("sertraline", order_code="", country="JP")
    assert concept["coding"][0]["code"] == "1179046"
    concept, _ = _resolve_medication_concept("mirtazapine 15mg", order_code="", country="JP")
    assert concept["coding"][0]["code"] == "1179051"
    # A case-ambiguous name keeps its exact-case code.
    concept, _ = _resolve_medication_concept("Lactulose 30mL", order_code="", country="JP")
    assert concept["coding"][0]["code"] in {"3999001", "3999001Q2058"}
