"""Unit tests for ServiceRequest builder polymorphic dispatch (Tier 1 #2 PR1).

Tests cover:
- IMAGING Order → single SR with correct category (SNOMED 363679005 + RAD).
- bodySite emission from imaging_body_site_code.
- code sourced from LOINC with body_sites.yaml display fallback (including JP).
- Status mapping via _map_order_status_to_sr_status (1:1, no aggregation).
- Polymorphic dispatch: LAB + IMAGING orders both emit SRs in the same call.
- Dict-path coverage (production JSON-deserialized CIF path).

PR1 LAB SR path regression: existing test_fhir_service_request.py covers it;
the ``test_lab_and_imaging_both_emit_when_both_present`` test here guards the
dispatch boundary.
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

from clinosim.modules.output._fhir_service_request import (
    IMAGING_CATEGORY_SNOMED,
    IMAGING_CATEGORY_V2_0074,
    LAB_CATEGORY_SNOMED,
    SR_ID_PREFIX,
    _bb_service_requests,
)
from clinosim.types.encounter import Order, OrderStatus, OrderType


def _make_ctx(orders, country="us"):
    return SimpleNamespace(
        record={"orders": orders},
        country=country,
        patient_id="pt1",
        primary_enc_id="enc1",
        roster_map={}, hospital_config={},
        patient_data={}, is_readmission=False, prior_encounter_id=None,
        primary_dx_code="", admit_dx_code="",
    )


def _imaging_order(order_id="ord1"):
    return Order(
        order_id=order_id, encounter_id="enc1", patient_id="pt1",
        order_type=OrderType.IMAGING, order_code="36572-6",
        display_name="Chest X-ray PA and Lateral",
        urgency="routine", clinical_intent="Suspected pneumonia",
        ordered_datetime=datetime(2026, 6, 30, 8, 30),
        status=OrderStatus.PLACED,
        imaging_modality="CR", imaging_body_site_code="51185008",
        imaging_views=["PA", "Lateral"],
    )


def test_emits_one_sr_per_imaging_order():
    ctx = _make_ctx([_imaging_order()])
    resources = _bb_service_requests(ctx)
    assert len(resources) == 1
    sr = resources[0]
    assert sr["resourceType"] == "ServiceRequest"
    assert sr["id"] == f"{SR_ID_PREFIX}ord1"


def test_imaging_sr_category_dual_coding():
    """category must carry both SNOMED 363679005 + HL7 v2-0074 RAD (AD-46)."""
    ctx = _make_ctx([_imaging_order()])
    sr = _bb_service_requests(ctx)[0]
    coding = sr["category"][0]["coding"]
    assert any(c["code"] == IMAGING_CATEGORY_SNOMED for c in coding)
    assert any(c["code"] == IMAGING_CATEGORY_V2_0074 for c in coding)


def test_imaging_sr_carries_body_site():
    ctx = _make_ctx([_imaging_order()])
    sr = _bb_service_requests(ctx)[0]
    bs = sr.get("bodySite") or []
    assert bs
    assert bs[0]["coding"][0]["code"] == "51185008"


def test_imaging_sr_code_uses_loinc():
    """Order.order_code = LOINC '36572-6' → SR.code.coding[0].system = LOINC system."""
    ctx = _make_ctx([_imaging_order()])
    sr = _bb_service_requests(ctx)[0]
    coding = sr["code"]["coding"][0]
    assert coding["code"] == "36572-6"
    assert "loinc" in coding["system"]


def test_imaging_sr_status_maps_placed_to_active():
    ctx = _make_ctx([_imaging_order()])
    sr = _bb_service_requests(ctx)[0]
    assert sr["status"] == "active"


def test_imaging_sr_status_maps_cancelled_to_revoked():
    o = _imaging_order()
    o.status = OrderStatus.CANCELLED
    ctx = _make_ctx([o])
    sr = _bb_service_requests(ctx)[0]
    assert sr["status"] == "revoked"


def test_imaging_sr_status_maps_resulted_to_completed():
    o = _imaging_order()
    o.status = OrderStatus.RESULTED
    ctx = _make_ctx([o])
    sr = _bb_service_requests(ctx)[0]
    assert sr["status"] == "completed"


def test_lab_and_imaging_both_emit_when_both_present():
    """Polymorphic dispatch — LAB + IMAGING orders both emit SRs in same call."""
    lab = Order(
        order_id="lab1", encounter_id="enc1", patient_id="pt1",
        order_type=OrderType.LAB, order_code="6690-2",
        display_name="WBC", urgency="routine",
        ordered_datetime=datetime(2026, 6, 30, 8, 0),
        status=OrderStatus.PLACED,
    )
    imaging = _imaging_order()
    ctx = _make_ctx([lab, imaging])
    resources = _bb_service_requests(ctx)
    assert len(resources) == 2
    categories = []
    for r in resources:
        cat_codes = {c["code"] for c in r["category"][0]["coding"]}
        if LAB_CATEGORY_SNOMED in cat_codes:
            categories.append("LAB")
        elif IMAGING_CATEGORY_SNOMED in cat_codes:
            categories.append("IMAGING")
    assert sorted(categories) == ["IMAGING", "LAB"]


def test_imaging_sr_clinical_intent_emitted_as_reason_code():
    ctx = _make_ctx([_imaging_order()])
    sr = _bb_service_requests(ctx)[0]
    reason = sr.get("reasonCode", [])
    assert reason and reason[0]["text"] == "Suspected pneumonia"


def test_imaging_sr_authored_on_present():
    ctx = _make_ctx([_imaging_order()])
    sr = _bb_service_requests(ctx)[0]
    assert "authoredOn" in sr
    assert sr["authoredOn"].startswith("2026-06-30")


def test_jp_locale_resolves_procedure_display_ja():
    """JP cohort: SR.code display uses body_sites.yaml display_ja via fallback."""
    ctx = _make_ctx([_imaging_order()], country="jp")
    sr = _bb_service_requests(ctx)[0]
    coding = sr["code"]["coding"][0]
    # body_sites.yaml: chest CR_PA_Lateral display_ja = "胸部単純X線撮影 正面・側面"
    # The text field carries Order.display_name (en); coding.display comes from
    # body_sites procedure display_ja when LOINC code is not in loinc.yaml.
    combined = coding["display"] + sr["code"].get("text", "")
    assert any(jp_char in combined for jp_char in ["胸", "正面", "撮影"])


# ---------------------------------------------------------------------------
# Dict-path coverage (production CIF is JSON-deserialized → plain dicts)
# ---------------------------------------------------------------------------


def test_imaging_sr_from_dict_path():
    """Production path: Order arrives as a JSON-deserialized dict, not a dataclass."""
    order_dict = {
        "order_id": "dict-ord1",
        "encounter_id": "enc1",
        "patient_id": "pt1",
        "order_type": "imaging",          # string, not OrderType.IMAGING
        "order_code": "36572-6",
        "display_name": "Chest X-ray PA and Lateral",
        "urgency": "routine",
        "clinical_intent": "Eval for pneumonia",
        "ordered_datetime": "2026-06-30T08:30:00",
        "status": "placed",               # string, not OrderStatus.PLACED
        "imaging_modality": "CR",
        "imaging_body_site_code": "51185008",
        "imaging_views": ["PA", "Lateral"],
    }
    ctx = _make_ctx([order_dict])
    resources = _bb_service_requests(ctx)
    assert len(resources) == 1
    sr = resources[0]
    assert sr["resourceType"] == "ServiceRequest"
    assert sr["id"] == f"{SR_ID_PREFIX}dict-ord1"
    # category must carry IMAGING codes
    coding = sr["category"][0]["coding"]
    assert any(c["code"] == IMAGING_CATEGORY_SNOMED for c in coding)
    # bodySite must be emitted
    assert sr.get("bodySite") and sr["bodySite"][0]["coding"][0]["code"] == "51185008"
    # status maps correctly
    assert sr["status"] == "active"


def test_imaging_sr_no_body_site_when_code_empty():
    """bodySite gate: empty imaging_body_site_code -> no bodySite field
    (silent-no-op defense against future regression where empty code emits
    `bodySite: [{"coding": [{"code": "", ...}]}]` = FHIR-invalid)."""
    o = _imaging_order()
    o.imaging_body_site_code = ""
    ctx = _make_ctx([o])
    sr = _bb_service_requests(ctx)[0]
    assert "bodySite" not in sr
