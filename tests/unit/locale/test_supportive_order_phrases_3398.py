"""Issue #3398: JP supportive-care orders read as Japanese clinical phrases.

Every disease-protocol ``admission_orders.supportive`` entry has a phrase of its
own in the procedure phrase table, looked up by its whole ``type: detail`` order
string before the type is translated, so a JP note never carries English words
or a word-by-word substitution of the English detail.
"""

from __future__ import annotations

import glob
import re
from pathlib import Path
from typing import Any

import pytest
import yaml

from clinosim.locale.free_text import localize_drug_name, localize_procedure_name, lookup_procedure_phrase
from clinosim.modules.order.engine import is_drugs_section_pointer, supportive_detail_raw
from clinosim.modules.order.treatment_classifier import classify_inpatient_supportive
from clinosim.types.encounter import OrderType
from tests.unit.modules.document.narrative.test_jp_no_english_words_3034 import _english_words

pytestmark = pytest.mark.unit

_REPO = Path(__file__).resolve().parents[3]
_WORD = re.compile(r"[A-Za-z][a-z]+")


def _supportive_entries() -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "supportive" and isinstance(value, list):
                    found.extend(e for e in value if isinstance(e, dict))
                else:
                    walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    for path in sorted(glob.glob(str(_REPO / "clinosim/modules/*/reference_data/**/*.yaml"), recursive=True)):
        try:
            walk(yaml.safe_load(Path(path).read_text(encoding="utf-8")))
        except yaml.YAMLError:
            continue
    return found


def _order_strings() -> dict[str, bool]:
    """``{CIF display_name: is_medication}`` of every supportive entry, in both countries."""
    out: dict[str, bool] = {}
    for entry in _supportive_entries():
        for country in ("JP", "US"):
            detail = supportive_detail_raw(entry, country)
            if is_drugs_section_pointer(detail):
                continue  # not an order (Issue #3596)
            kind = classify_inpatient_supportive(detail, entry.get("type", ""))
            out[f"{entry['type']}: {detail}"] = kind == OrderType.MEDICATION
    return out


def test_inventory_is_not_empty() -> None:
    assert len(_order_strings()) > 100


def test_every_supportive_order_reads_as_japanese() -> None:
    """Each order has a phrase (a therapy/procedure by the procedure table; a drug order
    by the drug path) and its JP text carries no English beyond the allowed abbreviations."""
    missing: list[str] = []
    english: list[str] = []
    for key, is_medication in _order_strings().items():
        ja = localize_drug_name(key, "ja") if is_medication else localize_procedure_name(key, "ja")
        if not is_medication and lookup_procedure_phrase(key, "ja") is None:
            missing.append(key)
        if _english_words(ja):
            english.append(f"{key} -> {ja}")
    assert not missing, "no JA phrase in clinosim-procedure-phrase.yaml:\n" + "\n".join(missing)
    assert not english, "English left in JP:\n" + "\n".join(english)


def test_us_output_is_unchanged_english() -> None:
    for key in _order_strings():
        out = localize_procedure_name(key, "en")
        assert not re.search(r"[぀-ヿ一-鿿]", out), out


@pytest.mark.parametrize(
    ("key", "ja"),
    [
        ("IV_fluid_restriction: Restrict to 1000 mL/day", "水分制限 1,000 mL/日"),
        ("diet: Low sodium (6g/day)", "減塩食 (6 g/日)"),
        ("limb_elevation: Elevate affected limb above heart level", "患肢挙上 (心臓より高く)"),
        ("wound_marking: Mark borders of erythema with skin marker", "発赤範囲をマーキング"),
        (
            "BP_management: Target SBP < 140 mmHg per AHA/ASA guidelines",
            "血圧管理: 目標 SBP < 140 mmHg (AHA/ASA ガイドライン)",
        ),
    ],
)
def test_phrases_are_clinical_japanese(key: str, ja: str) -> None:
    assert localize_procedure_name(key, "ja") == ja


def test_full_type_detail_key_is_looked_up_before_the_type_is_translated() -> None:
    # The type slug "IV_fluid_restriction" has its own med_terms name; the table key keeps it intact.
    assert lookup_procedure_phrase("IV_fluid_restriction: Restrict to 1000 mL/day", "ja") == "水分制限 1,000 mL/日"
    assert lookup_procedure_phrase("IV fluid restriction: restrict to 1000 ml/day", "ja") == "水分制限 1,000 mL/日"
    assert lookup_procedure_phrase("Restrict to 1000 mL/day", "ja") is None


def test_unknown_detail_renders_the_type_name_only() -> None:
    out = localize_procedure_name("fluid_restriction: Some brand new English detail we never translated", "ja")
    assert out == "水分制限"
    assert not _WORD.search(out)


def test_medication_path_leaks_are_whole_phrases() -> None:
    assert localize_drug_name("lactulose: 30mL PO TID if encephalopathy", "ja") == (
        "ラクツロース: 30mL 経口 1日3回 (肝性脳症がある場合)"
    )
    assert "NSAIDs" in localize_drug_name("pain_management: Acetaminophen 1000mg IV + NSAIDs", "ja")
    assert "until" not in localize_drug_name("IV_fluid: Lactated Ringer's 75-100 mL/h until oral intake", "ja")


def test_aha_asa_is_never_aspirin() -> None:
    assert "アスピリン" not in localize_procedure_name(
        "BP_management: Target SBP < 140 mmHg per AHA/ASA guidelines", "ja"
    )
