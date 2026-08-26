"""Issue #871: ServiceRequest.reasonCode.text JA localization via
`Order.clinical_intent_ja`.

Pre-fix (iris4h-ai 2026-08-26 deploy verify): 274,806 / 274,806 (100 %) of
JP `ServiceRequest.reasonCode.text` shipped the English CIF
`Order.clinical_intent` verbatim. The CIF field is behavior-load-bearing
(consumed by `_sr_intent_from_clinical_intent`,
`medication_pipeline._determine_route`, `validator.consistency`,
`medications.py` gates) so it CANNOT be localized in place.

Fix (this PR): add parallel display-only slot `Order.clinical_intent_ja`
(default ""). Writers populate BOTH fields; the SR emit reader
(`_pick_reason_text`) prefers `clinical_intent_ja` on JP output when
populated, else falls back to the EN `clinical_intent`. Empty JA slot
preserves pre-fix behavior for any writer that has not been migrated.

Same writer/reader locale-split pattern as `Encounter.chief_complaint` /
`Encounter.chief_complaint_ja` (Issue #360 G1).
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from typing import Any

import pytest

from clinosim.modules.output.fhir_r4.labs.service_request import (
    _bb_service_requests,
    _pick_reason_text,
)
from clinosim.types.encounter import Order, OrderStatus, OrderType

pytestmark = pytest.mark.unit


# === _pick_reason_text predicate ===


def test_pick_reason_text_prefers_ja_when_jp_and_populated() -> None:
    order = Order(clinical_intent="Chronic monitoring", clinical_intent_ja="慢性モニタリング")
    assert _pick_reason_text(order, "ja") == "慢性モニタリング"


def test_pick_reason_text_falls_back_to_en_when_jp_but_ja_empty() -> None:
    """Writer has not migrated yet — silent-no-op fallback preserves pre-#871
    behavior so JP output still shows something rather than an empty field."""
    order = Order(clinical_intent="Chronic monitoring", clinical_intent_ja="")
    assert _pick_reason_text(order, "ja") == "Chronic monitoring"


def test_pick_reason_text_en_locale_ignores_ja_slot() -> None:
    """US locale reads the EN field regardless of `clinical_intent_ja` — the
    JA slot is display-only and must not leak into US output."""
    order = Order(clinical_intent="Chronic monitoring", clinical_intent_ja="慢性モニタリング")
    assert _pick_reason_text(order, "en") == "Chronic monitoring"


def test_pick_reason_text_dict_shape_accepted() -> None:
    """Dual-access path — JSON-deserialized dict, not dataclass — is
    supported by the underlying ``_o`` helper."""
    order_dict = {"clinical_intent": "ED workup", "clinical_intent_ja": "救急外来精査"}
    assert _pick_reason_text(order_dict, "ja") == "救急外来精査"
    assert _pick_reason_text(order_dict, "en") == "ED workup"


def test_pick_reason_text_empty_both_fields_returns_empty() -> None:
    order = Order(clinical_intent="", clinical_intent_ja="")
    assert _pick_reason_text(order, "ja") == ""
    assert _pick_reason_text(order, "en") == ""


# === End-to-end via _bb_service_requests ===


def _ctx_with_lab_order(order: Order, country: str = "JP") -> Any:
    """Minimal BundleContext-shape fixture for _bb_service_requests."""
    from clinosim.modules.output.fhir_r4.lib.common import BundleContext

    record = {"orders": [order]}
    return BundleContext(
        record=record,
        country=country,
        roster_map={},
        hospital_config={},
        patient_data={},
        patient_id=order.patient_id or "pt-1",
        is_readmission=False,
        prior_encounter_id=None,
        primary_dx_code="",
        admit_dx_code="",
        admit_dx_system="icd-10-cm",
        primary_enc_id=order.encounter_id or "enc-1",
        patient_sex="F",
    )


def _stand_alone_lab_order(clinical_intent: str, clinical_intent_ja: str = "") -> Order:
    """Build a stand-alone lab Order that hits the `_build_standalone_sr` path
    (panel_key empty)."""
    return Order(
        order_id="ORD-enc-1-L01",
        encounter_id="enc-1",
        patient_id="pt-1",
        order_type=OrderType.LAB,
        order_code="2160-0",
        display_name="Creatinine",
        urgency="routine",
        clinical_intent=clinical_intent,
        clinical_intent_ja=clinical_intent_ja,
        ordered_datetime=datetime(2026, 6, 1, 10, 0),
        ordered_by="dr-1",
        status=OrderStatus.PLACED,
    )


def test_sr_emit_jp_uses_ja_reasoncode_when_populated() -> None:
    order = _stand_alone_lab_order(
        clinical_intent="Chronic-medication monitoring (Atorvastatin): Statin hepatotoxicity monitoring",
        clinical_intent_ja="慢性投薬モニタリング (アトルバスタチン): スタチン肝毒性モニタリング",
    )
    srs = _bb_service_requests(_ctx_with_lab_order(order, country="JP"))
    assert len(srs) == 1
    assert srs[0]["reasonCode"][0]["text"] == "慢性投薬モニタリング (アトルバスタチン): スタチン肝毒性モニタリング"


def test_sr_emit_jp_falls_back_to_en_when_ja_empty() -> None:
    """Pre-#871 behavior preserved for writers not yet migrated: JP output
    reads EN when JA slot is empty."""
    order = _stand_alone_lab_order(
        clinical_intent="Chronic-medication monitoring (Atorvastatin): Statin hepatotoxicity monitoring",
        clinical_intent_ja="",
    )
    srs = _bb_service_requests(_ctx_with_lab_order(order, country="JP"))
    assert len(srs) == 1
    assert (
        srs[0]["reasonCode"][0]["text"]
        == "Chronic-medication monitoring (Atorvastatin): Statin hepatotoxicity monitoring"
    )


def test_sr_emit_us_ignores_ja_slot() -> None:
    """US output MUST use the EN field even when JA is populated —
    regression pin against future accidental swap."""
    order = _stand_alone_lab_order(
        clinical_intent="Chronic-medication monitoring (Atorvastatin): Statin hepatotoxicity monitoring",
        clinical_intent_ja="慢性投薬モニタリング (アトルバスタチン): スタチン肝毒性モニタリング",
    )
    srs = _bb_service_requests(_ctx_with_lab_order(order, country="US"))
    assert len(srs) == 1
    assert (
        srs[0]["reasonCode"][0]["text"]
        == "Chronic-medication monitoring (Atorvastatin): Statin hepatotoxicity monitoring"
    )


def test_sr_intent_mapping_still_reads_en_field() -> None:
    """Regression pin: `_sr_intent_from_clinical_intent` (SR.intent mapping)
    must keep reading the EN `clinical_intent` — the JA slot is display-only
    and must NOT drive intent behavior. A JA-only order still uses the EN
    fallback for the intent code."""
    from clinosim.modules.output.fhir_r4.labs.service_request import (
        _sr_intent_from_clinical_intent,
    )

    # EN carries the behavior hint ("ed workup" → original-order); JA-only
    # ordering here would break intent selection if the reader used JA.
    assert _sr_intent_from_clinical_intent("ED workup: CBC") == "original-order"
    assert _sr_intent_from_clinical_intent("Outpatient follow-up: Cr") == "instance-order"
    assert _sr_intent_from_clinical_intent("Admission workup: Na") == "order"


# === Monitoring enricher end-to-end (dominant volume — verifies YAML +
# writer + reader wiring end-to-end for the largest source) ===


def test_monitoring_enricher_composes_ja_intent() -> None:
    """Full pipeline: monitoring enricher on a chronic-med patient produces
    an Order whose `clinical_intent_ja` composes the YAML `drug_ja` and
    `rationale_ja` into the JA template."""
    import numpy as np

    from clinosim.modules.monitoring.enricher import (
        _inject_one_lab,
    )

    record = SimpleNamespace(orders=[], lab_results=[])
    encounter = SimpleNamespace(
        encounter_id="enc-1",
        attending_physician_id="dr-1",
        admission_datetime=datetime(2026, 6, 1, 9, 0),
    )
    patient = SimpleNamespace(patient_id="pt-1", sex="F", age=60, chronic_conditions=[])
    _inject_one_lab(
        record=record,
        encounter=encounter,
        patient=patient,
        analyte="AST",
        display_name="AST",
        loinc="1920-8",
        rationale=(
            "Statin hepatotoxicity monitoring — AST/ALT baseline + as clinically indicated "
            "(myalgia, muscle-weakness). ACC/AHA 2018 + JAS 2022 guideline."
        ),
        rationale_ja=(
            "スタチン肝毒性モニタリング — AST/ALT はベースライン取得後、筋痛・筋力低下等の臨床所見が"
            "出た時に再検。ACC/AHA 2018 + JAS 2022 ガイドライン準拠。"
        ),
        drug="Atorvastatin",
        drug_ja="アトルバスタチン",
        true_value=25.0,
        enricher_rng=np.random.default_rng(42),
        country="JP",
        injected_index=0,
    )
    assert len(record.orders) == 1
    order = record.orders[0]
    assert order.clinical_intent.startswith("Chronic-medication monitoring (Atorvastatin):")
    assert order.clinical_intent_ja.startswith("慢性投薬モニタリング (アトルバスタチン):")


def test_monitoring_enricher_empty_rationale_ja_leaves_slot_empty() -> None:
    """Silent-no-op fallback: when the YAML has no `rationale_ja` (i.e. an
    entry that has not been bilingually authored yet), the enricher leaves
    `Order.clinical_intent_ja` empty so the SR emit falls back to EN."""
    import numpy as np

    from clinosim.modules.monitoring.enricher import _inject_one_lab

    record = SimpleNamespace(orders=[], lab_results=[])
    encounter = SimpleNamespace(
        encounter_id="enc-1",
        attending_physician_id="dr-1",
        admission_datetime=datetime(2026, 6, 1, 9, 0),
    )
    patient = SimpleNamespace(patient_id="pt-1", sex="F", age=60, chronic_conditions=[])
    _inject_one_lab(
        record=record,
        encounter=encounter,
        patient=patient,
        analyte="AST",
        display_name="AST",
        loinc="1920-8",
        rationale="Some EN rationale",
        rationale_ja="",  # NOT authored
        drug="Atorvastatin",
        drug_ja="アトルバスタチン",
        true_value=25.0,
        enricher_rng=np.random.default_rng(42),
        country="JP",
        injected_index=0,
    )
    assert len(record.orders) == 1
    assert record.orders[0].clinical_intent_ja == ""


# === YAML integrity guard: every rationale in medication_monitoring.yaml
# has a JA sibling (2026-08-26 baseline — 8 rationale entries) ===


def test_medication_monitoring_yaml_has_rationale_ja_on_every_entry() -> None:
    """Coverage guard: every drug entry in `medication_monitoring.yaml`
    carries `drug_ja`, and every `monitoring[]` entry carries `rationale_ja`.

    Detects a future accidental deletion or a new drug entry that ships
    without JA authoring (which would silently EN-leak on JP output)."""
    from clinosim.modules.monitoring.mapping import load_medication_monitoring

    mapping = load_medication_monitoring()

    drugs_without_drug_ja = [drug for drug, spec in mapping.items() if not spec.get("drug_ja")]
    assert not drugs_without_drug_ja, (
        f"Drug entries missing `drug_ja` in medication_monitoring.yaml: {drugs_without_drug_ja}"
    )

    monitoring_without_rationale_ja: list[tuple[str, str]] = []
    for drug, spec in mapping.items():
        for lab_spec in spec.get("monitoring", []) or []:
            if not lab_spec.get("rationale_ja"):
                monitoring_without_rationale_ja.append((drug, lab_spec.get("lab", "?")))
    assert not monitoring_without_rationale_ja, (
        f"Monitoring entries missing `rationale_ja` in medication_monitoring.yaml: {monitoring_without_rationale_ja}"
    )


def test_medication_monitoring_yaml_ja_values_contain_japanese_characters() -> None:
    """Guard against an accidental EN string in a `_ja` slot."""
    import re

    from clinosim.modules.monitoring.mapping import load_medication_monitoring

    ja_char_re = re.compile(r"[぀-ゟ゠-ヿ一-鿿]")
    mapping = load_medication_monitoring()

    en_in_ja: list[tuple[str, str, str]] = []
    for drug, spec in mapping.items():
        drug_ja = spec.get("drug_ja") or ""
        if drug_ja and not ja_char_re.search(drug_ja):
            en_in_ja.append((drug, "drug_ja", drug_ja))
        for lab_spec in spec.get("monitoring", []) or []:
            rat_ja = lab_spec.get("rationale_ja") or ""
            if rat_ja and not ja_char_re.search(rat_ja):
                en_in_ja.append((drug, f"monitoring[{lab_spec.get('lab', '?')}].rationale_ja", rat_ja))
    assert not en_in_ja, f"YAML `_ja` slots that appear to be EN (no Japanese chars): {en_in_ja}"
