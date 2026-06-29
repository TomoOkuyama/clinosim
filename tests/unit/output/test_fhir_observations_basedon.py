"""Tests for Observation.basedOn linkage to ServiceRequest (PR1)."""

from datetime import datetime

from clinosim.modules.output._fhir_common import BundleContext
from clinosim.modules.output._fhir_observations import _bb_labs
from clinosim.types.encounter import Order, OrderResult, OrderStatus, OrderType


def _make_lab_order(order_id, panel_key, lab_name, value, t):
    o = Order(
        order_id=order_id,
        encounter_id="enc1",
        patient_id="pt1",
        order_type=OrderType.LAB,
        order_code="6690-2",
        display_name=lab_name,
        ordered_datetime=t,
        ordered_by="doc1",
        status=OrderStatus.RESULTED,
        panel_key=panel_key,
    )
    o.result = OrderResult(
        result_datetime=t,
        performed_by="tech1",
        lab_name=lab_name,
        value=value,
        unit="x10^3/uL",
    )
    return o


def _make_ctx(orders):
    return BundleContext(
        record={"orders": orders},
        country="us",
        roster_map={},
        hospital_config={},
        patient_data={},
        patient_id="pt1",
        is_readmission=False,
        prior_encounter_id=None,
        primary_dx_code="",
        admit_dx_code="",
        admit_dx_system="",
        primary_enc_id="enc1",  # must match order.encounter_id (assert in _build_lab_observation)
        patient_sex="",
    )


def test_lab_observation_has_basedon_panel():
    """Panel lab Observation → basedOn references panel SR."""
    t = datetime(2026, 6, 29, 8, 5)
    orders = [
        _make_lab_order(f"O{i}", "CBC", name, 6.0, t)
        for i, name in enumerate(["WBC", "Hb", "Hct", "Plt"])
    ]
    ctx = _make_ctx(orders)
    obs = _bb_labs(ctx)
    lab_obs = [o for o in obs if o.get("resourceType") == "Observation"]
    assert len(lab_obs) == 4
    for o in lab_obs:
        assert "basedOn" in o
        assert o["basedOn"] == [{"reference": "ServiceRequest/sr-enc1-CBC-1"}]


def test_lab_observation_has_basedon_standalone():
    """Stand-alone lab Observation → basedOn references its own SR."""
    t = datetime(2026, 6, 29, 8, 5)
    o = _make_lab_order("ORD-pt1-ADM-L05", "", "Troponin_I", 0.05, t)
    ctx = _make_ctx([o])
    obs = _bb_labs(ctx)
    assert obs[0]["basedOn"] == [{"reference": "ServiceRequest/sr-ORD-pt1-ADM-L05"}]


# === Production-path dict tests (Fix 2: basedOn now populated for dict orders) ===
# These tests verify that the previously silent omission (sr_id = None on dict path)
# is fixed. Dict orders are what json.load() produces in production CIF.

def _make_dict_lab_order(order_id: str, panel_key: str, lab_name: str,
                          value: float) -> dict:
    """Dict-style order with a result, matching json.load() CIF output."""
    t = "2026-06-29T08:05:00"
    return {
        "order_id": order_id,
        "encounter_id": "enc1",
        "patient_id": "pt1",
        "order_type": "lab",
        "order_code": "6690-2",
        "display_name": lab_name,
        "urgency": "routine",
        "clinical_intent": "test",
        "ordered_datetime": t,
        "ordered_by": "doc1",
        "status": "resulted",
        "panel_key": panel_key,
        "result": {
            "result_datetime": t,
            "performed_by": "tech1",
            "lab_name": lab_name,
            "value": value,
            "unit": "x10^3/uL",
        },
    }


def test_lab_observation_basedon_dict_input_panel():
    """Production-path: Observation.basedOn populated for dict-style panel Orders."""
    orders = [
        _make_dict_lab_order(f"O{i}", "CBC", name, 6.0)
        for i, name in enumerate(["WBC", "Hb", "Hct", "Plt"])
    ]
    ctx = _make_ctx(orders)  # type: ignore[arg-type]
    obs = _bb_labs(ctx)
    lab_obs = [o for o in obs if o.get("resourceType") == "Observation"]
    assert len(lab_obs) > 0
    for o in lab_obs:
        assert "basedOn" in o, f"basedOn missing from {o.get('id')}"
        assert o["basedOn"][0]["reference"] == "ServiceRequest/sr-enc1-CBC-1"


def test_lab_observation_basedon_dict_input_standalone():
    """Production-path: Observation.basedOn populated for dict-style stand-alone Order."""
    orders = [_make_dict_lab_order("ORD-pt1-ADM-L05", "", "Troponin_I", 0.05)]
    ctx = _make_ctx(orders)  # type: ignore[arg-type]
    obs = _bb_labs(ctx)
    assert len(obs) > 0
    assert obs[0]["basedOn"] == [{"reference": "ServiceRequest/sr-ORD-pt1-ADM-L05"}]
