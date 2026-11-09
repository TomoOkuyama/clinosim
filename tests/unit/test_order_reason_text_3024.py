"""Issue #3024: an order reason states the clinical reason in the output
language — no clinical-course archetype key, no English analyte or English
imaging reason in a Japanese reason (code-mapping spec section 6)."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

import numpy as np
import pytest
import yaml

from clinosim.locale.i18n import t
from clinosim.locale.loader import load_narrative_archetypes, order_test_display
from clinosim.modules.disease.protocol import load_disease_protocol
from clinosim.modules.order.engine import place_admission_orders, place_imaging_orders

pytestmark = pytest.mark.unit

_JA = re.compile(r"[぀-ヿ一-鿿]")
_ARCHETYPE_KEYS = set(load_narrative_archetypes() or {})
_ENGLISH_ANALYTES = ("Creatinine", "Glucose", "Troponin", "Albumin", "Lactate", "Potassium", "Sodium")


@pytest.mark.parametrize(
    "key",
    [
        "archetype_workup",
        "archetype_imaging",
        "archetype_new_medication",
        "archetype_device",
        "archetype_procedure",
    ],
)
@pytest.mark.parametrize("lang", ["ja", "en"])
def test_a_follow_up_order_reason_names_no_archetype_key(key: str, lang: str) -> None:
    text = t(f"order_intent.{key}", lang, day=2)
    assert "{" not in text and not any(k in text for k in _ARCHETYPE_KEYS)
    if lang == "ja":
        assert text.startswith("第2病日") and _JA.search(text)


def test_a_stop_reason_names_the_drug_in_japanese() -> None:
    from clinosim.locale.free_text import localize_drug_name

    text = t("order_intent.archetype_stop", "ja", day=3, drug=localize_drug_name("Ceftriaxone", "ja"))
    assert text == "第3病日 治療方針変更に伴うセフトリアキソン中止"


@pytest.mark.parametrize(
    ("test", "ja"),
    [("Creatinine", "クレアチニン"), ("Glucose", "血糖"), ("Chest_Xray", "胸部レントゲン"), ("PT_INR", "PT-INR")],
)
def test_order_test_display_is_the_japanese_test_name(test: str, ja: str) -> None:
    assert order_test_display(test, "ja") == ja


def test_a_jp_admission_lab_reason_has_no_english_analyte() -> None:
    protocol = load_disease_protocol("bacterial_pneumonia").model_dump()
    orders = place_admission_orders(protocol, "P1", "E1", datetime(2026, 3, 1, 9), "jp", np.random.default_rng(0))
    labs = [o for o in orders if o.order_type.value == "lab"]
    assert labs
    for o in labs:
        assert _JA.search(o.clinical_intent_ja), o.clinical_intent_ja
        assert not any(a in o.clinical_intent_ja for a in _ENGLISH_ANALYTES), o.clinical_intent_ja


def test_every_imaging_reason_has_a_japanese_text() -> None:
    root = Path(__file__).resolve().parents[2] / "clinosim" / "modules" / "disease" / "reference_data"
    missing = []
    for path in sorted(root.glob("*.yaml")):
        for spec in (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("imaging_orders") or []:
            reason = spec.get("clinical_indication")
            if reason and not (
                isinstance(reason, dict) and _JA.search(str(reason.get("ja") or "")) and reason.get("en")
            ):
                missing.append((path.stem, reason))
    assert missing == []


def test_a_jp_imaging_order_carries_the_japanese_reason() -> None:
    protocol = load_disease_protocol("bacterial_pneumonia")
    orders = place_imaging_orders(
        protocol, "E1", "P1", datetime(2026, 3, 1, 9), 0, "moderate", np.random.default_rng(0), {"I": 0}
    )
    assert orders
    assert orders[0].clinical_intent_ja == "肺炎疑い、浸潤影の評価"
