"""The remaining English free text in JP records is localized (Issue #3107).

ED imaging orders named by their LOINC display, NPO orders, surgery names,
DOAC dose conditions and the medication-hold / treatment-switch rationale
read in Japanese in JP output; English output is unchanged.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from clinosim.locale.free_text import localize_free_text
from clinosim.modules.document.narrative._localization import _localize_proc_type
from clinosim.modules.document.narrative.renderers.section_builders.discharge_summary import (
    build_discharge_medications,
)
from clinosim.modules.document.narrative.renderers.section_builders.ed_note import _ed_imaging_display
from clinosim.simulator.medication_pipeline import _hold_reason_japanese

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("loinc", "en", "ja"),
    [
        ("79103-8", "CT Abdomen W contrast IV", "腹部造影CT"),
        ("24628-0", "CT Chest W contrast IV", "胸部造影CT"),
        ("80861-8", "US Lower extremity soft tissue", "下肢軟部組織超音波"),
    ],
)
def test_an_ed_imaging_order_is_named_by_its_loinc_label(loinc: str, en: str, ja: str) -> None:
    order = {"order_code": loinc, "order_code_system": "loinc", "display_name": en}
    assert _ed_imaging_display(order, "ja") == ja
    assert _ed_imaging_display(order, "en") == en


@pytest.mark.parametrize(
    ("text", "ja"),
    [
        ("Nothing by mouth pending endoscopy", "内視鏡まで絶飲食"),
        ("Nothing by mouth for surgery", "術前絶飲食"),
        ("Nothing by mouth", "絶飲食"),
    ],
)
def test_npo_orders_are_japanese(text: str, ja: str) -> None:
    assert localize_free_text(text, "ja") == ja
    assert localize_free_text(text, "en") == text


@pytest.mark.parametrize(
    ("proc_type", "ja"),
    [
        ("hemiarthroplasty", "人工骨頭置換術"),
        ("laparoscopic appendectomy", "腹腔鏡下虫垂切除術"),
        ("laparoscopic cholecystectomy", "腹腔鏡下胆嚢摘出術"),
        ("ORIF", "観血的整復固定術"),
    ],
)
def test_surgery_names_are_japanese(proc_type: str, ja: str) -> None:
    assert _localize_proc_type(proc_type, "ja") == ja
    assert "_" not in _localize_proc_type(proc_type, "en")


def test_a_doac_dose_condition_uses_the_authored_japanese_text() -> None:
    med = {
        "drug_name": "Edoxaban",
        "dose": "60mg PO daily (30mg if CrCl 15-50 or weight <= 60kg)",
        "dose_ja": "60mg 1日1回 経口（CrCl 15-50 または体重 60kg 以下では 30mg）",
        "route": "PO",
    }
    ja, _ = build_discharge_medications(None, SimpleNamespace(target_lang="ja", discharge_medications=[med]))
    assert "体重 60kg 以下" in ja and "weight" not in ja
    en, _ = build_discharge_medications(None, SimpleNamespace(target_lang="en", discharge_medications=[med]))
    assert "weight <= 60kg" in en


def test_the_medication_hold_rationale_is_japanese() -> None:
    reason = "Acute HF exacerbation — oral diuretic replaced by IV furosemide"
    assert _hold_reason_japanese(reason) == "急性心不全増悪 (内服利尿薬を静注フロセミドに変更)"
    assert "PO" not in _hold_reason_japanese("Stroke: PO bisphosphonates held (aspiration risk)")


def test_admission_order_intents_name_drugs_and_categories_in_japanese() -> None:
    import re
    from datetime import datetime

    import numpy as np

    from clinosim.modules.disease.protocol import load_disease_protocol
    from clinosim.modules.order.engine import place_admission_orders

    orders = place_admission_orders(
        load_disease_protocol("influenza").model_dump(),
        "P1",
        "E1",
        datetime(2026, 1, 10, 9),
        country="japan",
        rng=np.random.default_rng(0),
    )
    meds = [o for o in orders if o.order_type.value == "medication"]
    assert meds
    for o in meds:
        assert not re.search(r"[A-Za-z][a-z]{3,}", o.clinical_intent_ja), o.clinical_intent_ja
        assert o.clinical_intent  # English kept


def test_diet_and_category_names() -> None:
    from clinosim.locale.loader import load_diet_type_display
    from clinosim.locale.localized import localized
    from clinosim.modules.order.engine import _category_name

    assert _category_name("IV_fluid", "ja") == "輸液"
    assert _category_name("antipyretic", "ja") == "解熱剤"
    assert localized(load_diet_type_display()["soft_diet"], "ja") == "軟菜食"


_LOWER_WORD = __import__("re").compile(r"(?<![A-Za-z0-9])[A-Za-z][a-z]+(?:-[a-z]+)*(?![A-Za-z0-9])")


@pytest.mark.parametrize(
    ("source", "section"),
    [
        ("locale/shared/medication_hold_reasons.yaml", "reasons"),
        ("codes/data/clinosim-procedure-catalog.yaml", "named"),
    ],
)
def test_japanese_labels_of_these_sources_have_no_english_words(source: str, section: str) -> None:
    from pathlib import Path

    import yaml

    import clinosim

    data = yaml.safe_load((Path(clinosim.__file__).parent / source).read_text(encoding="utf-8"))[section]
    entries = data.values() if isinstance(data, dict) else data
    for entry in entries:
        ja = (entry.get("name") or entry).get("ja", "")
        assert ja and not _LOWER_WORD.findall(ja), ja


def _protocol_yamls(subdir: str) -> list[dict]:
    from pathlib import Path

    import yaml

    import clinosim

    root = Path(clinosim.__file__).parent / "modules" / subdir / "reference_data"
    return [yaml.safe_load(p.read_text(encoding="utf-8")) or {} for p in sorted(root.glob("*.yaml"))]


def test_every_escalation_indication_has_a_japanese_label() -> None:
    from clinosim.locale.loader import narrative_label

    for proto in _protocol_yamls("disease"):
        esc = (proto.get("drugs") or {}).get("escalation") or {}
        for entries in esc.values() if isinstance(esc, dict) else []:
            for e in [entries] if isinstance(entries, dict) else entries or []:
                if isinstance(e, dict):
                    key = str(e.get("indication", "no improvement"))
                    ja = narrative_label("escalation_indication", key, "ja")
                    assert ja != key and not _LOWER_WORD.findall(ja), key


def test_every_ed_treatment_intent_has_a_japanese_label() -> None:
    from clinosim.locale.loader import treatment_intent_display

    for proto in _protocol_yamls("encounter"):
        for tx in proto.get("treatment") or []:
            intent = tx.get("intent") if isinstance(tx, dict) else None
            if intent:
                ja = treatment_intent_display(intent, "ja")
                assert ja != intent and not _LOWER_WORD.findall(ja), intent
                assert treatment_intent_display(intent, "en") == intent


def test_every_supportive_order_category_has_a_japanese_name() -> None:
    from clinosim.modules.order.engine import _category_name

    for proto in _protocol_yamls("disease"):
        adm = (proto.get("order_protocols") or {}).get("admission_orders") or {}
        for sup in adm.get("supportive") or []:
            if isinstance(sup, dict) and sup.get("type"):
                ja = _category_name(sup["type"], "ja")
                assert ja != sup["type"] or ja.isupper(), sup["type"]
                assert not _LOWER_WORD.findall(ja), (sup["type"], ja)


def test_drug_safety_japanese_rationales_have_no_english_words() -> None:
    from pathlib import Path

    import yaml

    import clinosim

    allowed = {"Na"}
    root = Path(clinosim.__file__).parent / "modules" / "drug_safety" / "reference_data"

    def walk(node: object, key: str = "") -> list[str]:
        if isinstance(node, dict):
            return [s for k, v in node.items() for s in walk(v, str(k))]
        if isinstance(node, list):
            return [s for v in node for s in walk(v, key)]
        return [node] if key == "ja" and isinstance(node, str) else []

    for path in sorted(root.glob("*.yaml")):
        for text in walk(yaml.safe_load(path.read_text(encoding="utf-8"))):
            words = [w for w in _LOWER_WORD.findall(text) if w not in allowed]
            assert not words, (path.name, words, text[:60])


def test_chemotherapy_dose_text_is_japanese() -> None:
    from clinosim.locale.free_text import _localize_dosage_terms

    assert (
        _localize_dosage_terms("400mg/m2 bolus + 2400mg/m2/46h", "ja") == "400mg/m² 急速静注後 2400mg/m² 46時間持続静注"
    )


def test_monitoring_rationales_carry_no_internal_issue_reference() -> None:
    from pathlib import Path

    import yaml

    import clinosim

    path = Path(clinosim.__file__).parent / "modules/monitoring/reference_data/medication_monitoring.yaml"

    def walk(node: object) -> list[str]:
        if isinstance(node, dict):
            return [s for k, v in node.items() for s in (walk(v) if k not in ("en", "ja") else [str(v)])]
        if isinstance(node, list):
            return [s for v in node for s in walk(v)]
        return []

    texts = walk(yaml.safe_load(path.read_text(encoding="utf-8")))
    assert texts and not [t for t in texts if "Issue #" in t]
