"""Unit tests for ServiceRequest FHIR builder (PR1)."""

from datetime import datetime

from clinosim.modules.output._fhir_service_request import (
    LAB_CATEGORY_SNOMED,
    LAB_CATEGORY_V2_0074,
    PLACER_ORDER_NUMBER_SYSTEM,
    SNOMED_CT_SYSTEM,
    SR_ID_PREFIX,
    V2_0203_SYSTEM,
    _bb_service_requests,
    aggregate_panel_status,
    build_panel_counter,
    order_to_sr_id,
)
from clinosim.types.encounter import Order, OrderStatus, OrderType


def test_canonical_constants():
    assert SR_ID_PREFIX == "sr-"
    assert PLACER_ORDER_NUMBER_SYSTEM == "urn:clinosim:placer-order-number"
    assert LAB_CATEGORY_SNOMED == "108252007"
    assert LAB_CATEGORY_V2_0074 == "LAB"


def _make_order(order_id="O1", panel_key="", status=OrderStatus.PLACED,
                encounter_id="enc1", ordered_datetime=None) -> Order:
    return Order(
        order_id=order_id,
        encounter_id=encounter_id,
        patient_id="pt1",
        order_type=OrderType.LAB,
        order_code="6690-2",
        display_name="WBC",
        ordered_datetime=ordered_datetime or datetime(2026, 6, 29, 8, 5),
        ordered_by="doc1",
        status=status,
        panel_key=panel_key,
    )


def test_order_to_sr_id_standalone():
    """Stand-alone Order → sr-{order_id}."""
    o = _make_order(order_id="ORD-pt1-ADM-L05", panel_key="")
    counter = build_panel_counter([o])
    assert order_to_sr_id(o, counter) == "sr-ORD-pt1-ADM-L05"


def test_order_to_sr_id_panel():
    """Panel Order → sr-{enc}-{panel_key}-{N}, N is encounter-scoped index."""
    t = datetime(2026, 6, 29, 8, 5)
    orders = [
        _make_order(order_id=f"O{i}", panel_key="CBC",
                    encounter_id="enc1", ordered_datetime=t) for i in range(4)
    ]
    counter = build_panel_counter(orders)
    for o in orders:
        assert order_to_sr_id(o, counter) == "sr-enc1-CBC-1"


def test_panel_counter_increments_per_panel_instance():
    """Same panel ordered twice in same encounter → counter 1, 2."""
    t1 = datetime(2026, 6, 29, 8, 5)
    t2 = datetime(2026, 7, 2, 8, 5)  # day 3
    orders = [
        _make_order(order_id=f"O{i}", panel_key="CBC",
                    encounter_id="enc1", ordered_datetime=t1) for i in range(4)
    ] + [
        _make_order(order_id=f"O{i+10}", panel_key="CBC",
                    encounter_id="enc1", ordered_datetime=t2) for i in range(4)
    ]
    counter = build_panel_counter(orders)
    # First instance (t1) = 1, second (t2) = 2
    assert counter[("enc1", "CBC", t1)] == 1
    assert counter[("enc1", "CBC", t2)] == 2
    assert order_to_sr_id(orders[0], counter) == "sr-enc1-CBC-1"
    assert order_to_sr_id(orders[4], counter) == "sr-enc1-CBC-2"


def test_build_panel_counter_input_order_independent():
    """build_panel_counter sorts internally; counter result is the same
    regardless of input list ordering."""
    t1 = datetime(2026, 6, 29, 8, 5)
    t2 = datetime(2026, 7, 2, 8, 5)
    orders_chronological = [
        _make_order(order_id=f"O{i}", panel_key="CBC",
                    encounter_id="enc1", ordered_datetime=t1) for i in range(4)
    ] + [
        _make_order(order_id=f"O{i+10}", panel_key="CBC",
                    encounter_id="enc1", ordered_datetime=t2) for i in range(4)
    ]
    # Reverse the input
    orders_reversed = list(reversed(orders_chronological))
    counter_chrono = build_panel_counter(orders_chronological)
    counter_reversed = build_panel_counter(orders_reversed)
    assert counter_chrono == counter_reversed
    # Both must assign the same N to the t1 and t2 panel instances
    assert counter_chrono[("enc1", "CBC", t1)] == 1
    assert counter_chrono[("enc1", "CBC", t2)] == 2


def test_aggregate_panel_status_all_resulted():
    members = [_make_order(status=OrderStatus.RESULTED) for _ in range(4)]
    assert aggregate_panel_status(members) == "completed"


def test_aggregate_panel_status_all_reviewed():
    members = [_make_order(status=OrderStatus.REVIEWED) for _ in range(4)]
    assert aggregate_panel_status(members) == "completed"


def test_aggregate_panel_status_all_cancelled():
    members = [_make_order(status=OrderStatus.CANCELLED) for _ in range(4)]
    assert aggregate_panel_status(members) == "revoked"


def test_aggregate_panel_status_all_stopped():
    members = [_make_order(status=OrderStatus.STOPPED) for _ in range(4)]
    assert aggregate_panel_status(members) == "revoked"


def test_aggregate_panel_status_mixed_terminal():
    """Mixed RESULTED + CANCELLED → completed (panel done, partial cancel)."""
    members = [
        _make_order(status=OrderStatus.RESULTED),
        _make_order(status=OrderStatus.RESULTED),
        _make_order(status=OrderStatus.RESULTED),
        _make_order(status=OrderStatus.CANCELLED),
    ]
    assert aggregate_panel_status(members) == "completed"


def test_aggregate_panel_status_any_non_terminal_yields_active():
    """Any IN_PROGRESS / PLACED / ACCEPTED → active."""
    members = [
        _make_order(status=OrderStatus.RESULTED),
        _make_order(status=OrderStatus.RESULTED),
        _make_order(status=OrderStatus.IN_PROGRESS),
        _make_order(status=OrderStatus.RESULTED),
    ]
    assert aggregate_panel_status(members) == "active"


def test_aggregate_panel_status_all_placed_yields_active():
    members = [_make_order(status=OrderStatus.PLACED) for _ in range(4)]
    assert aggregate_panel_status(members) == "active"


def test_aggregate_panel_status_single_member():
    """Stand-alone (treated as 1-member panel) → same rule."""
    assert aggregate_panel_status([_make_order(status=OrderStatus.RESULTED)]) == "completed"
    assert aggregate_panel_status([_make_order(status=OrderStatus.PLACED)]) == "active"
    assert aggregate_panel_status([_make_order(status=OrderStatus.CANCELLED)]) == "revoked"


def _make_ctx(orders: list[Order], country: str = "us"):
    """Minimal BundleContext for builder testing."""
    from clinosim.modules.output._fhir_common import BundleContext
    return BundleContext(
        record={"orders": orders},
        country=country,
        roster_map={},
        hospital_config={},
        patient_data={},
        patient_id="pt1",
        is_readmission=False,
        prior_encounter_id=None,
        primary_dx_code="",
        admit_dx_code="",
        admit_dx_system="",
        primary_enc_id="",
        patient_sex="",
    )


def test_bb_service_requests_panel_emits_single_sr():
    """4 CBC Orders → 1 ServiceRequest resource."""
    t = datetime(2026, 6, 29, 8, 5)
    orders = [
        _make_order(order_id=f"O{i}", panel_key="CBC",
                    encounter_id="enc1", ordered_datetime=t) for i in range(4)
    ]
    for o, name in zip(orders, ["WBC", "Hb", "Hct", "Plt"]):
        o.display_name = name
    ctx = _make_ctx(orders)
    resources = _bb_service_requests(ctx)
    assert len(resources) == 1
    sr = resources[0]
    assert sr["resourceType"] == "ServiceRequest"
    assert sr["id"] == "sr-enc1-CBC-1"
    assert sr["intent"] == "order"
    assert sr["code"]["text"] == "CBC"
    assert sr["code"]["coding"][0]["code"] == "58410-2"   # CBC LOINC panel code


def test_bb_service_requests_standalone_emits_one_sr_per_order():
    """3 stand-alone Orders → 3 ServiceRequest resources."""
    orders = [
        _make_order(order_id=f"ORD-pt1-ADM-L0{i}", panel_key="",
                    encounter_id="enc1") for i in range(3)
    ]
    ctx = _make_ctx(orders)
    resources = _bb_service_requests(ctx)
    assert len(resources) == 3
    ids = {r["id"] for r in resources}
    assert ids == {"sr-ORD-pt1-ADM-L00", "sr-ORD-pt1-ADM-L01", "sr-ORD-pt1-ADM-L02"}


def test_bb_service_requests_identifier_plac():
    """Every SR has identifier.type.coding PLAC + placer-order-number system."""
    orders = [_make_order(order_id="ORD-1", panel_key="")]
    ctx = _make_ctx(orders)
    sr = _bb_service_requests(ctx)[0]
    ident = sr["identifier"][0]
    assert ident["system"] == PLACER_ORDER_NUMBER_SYSTEM
    assert ident["type"]["coding"][0]["code"] == "PLAC"
    # Verify both the emitted URI AND that the canonical constant matches the spec
    assert ident["type"]["coding"][0]["system"] == "http://terminology.hl7.org/CodeSystem/v2-0203"
    assert ident["type"]["coding"][0]["system"] == V2_0203_SYSTEM


def test_bb_service_requests_category_dual_coding():
    """Every SR has dual coding: SNOMED 108252007 + v2-0074 LAB."""
    orders = [_make_order(order_id="ORD-1", panel_key="")]
    ctx = _make_ctx(orders)
    sr = _bb_service_requests(ctx)[0]
    coding = sr["category"][0]["coding"]
    codes = {c["code"] for c in coding}
    assert codes == {LAB_CATEGORY_SNOMED, LAB_CATEGORY_V2_0074}
    # Verify SNOMED URI
    snomed_coding = next(c for c in coding if c["code"] == LAB_CATEGORY_SNOMED)
    assert snomed_coding["system"] == "http://snomed.info/sct"
    assert snomed_coding["system"] == SNOMED_CT_SYSTEM


def test_bb_service_requests_jp_locale_uses_ja_snomed_display():
    """JP cohort SR has SNOMED display in Japanese."""
    orders = [_make_order(order_id="ORD-1", panel_key="")]
    ctx = _make_ctx(orders, country="jp")
    sr = _bb_service_requests(ctx)[0]
    snomed_coding = next(c for c in sr["category"][0]["coding"]
                          if c["code"] == LAB_CATEGORY_SNOMED)
    assert snomed_coding["display"] == "臨床検査"


def test_bb_service_requests_empty_orders_returns_empty():
    """No lab Orders → no SR."""
    ctx = _make_ctx([])
    assert _bb_service_requests(ctx) == []


def test_bb_service_requests_skips_non_lab_orders():
    """MEDICATION / IMAGING / etc. Orders are ignored."""
    o_med = _make_order(order_id="M1")
    o_med.order_type = OrderType.MEDICATION
    o_img = _make_order(order_id="I1")
    o_img.order_type = OrderType.IMAGING
    ctx = _make_ctx([o_med, o_img])
    assert _bb_service_requests(ctx) == []
