"""Regression test for _build_lab_observation's code-system/value pairing.

`code_value` is resolved via `code_map.get(lab_name, order.get("order_code", ""))`
while `code_system_key` is computed once from country alone. If a lab_name isn't in
the country's code_mapping_lab.yaml, the fallback order_code (LOINC-shaped) must be
tagged with the LOINC system, not the country's mapped system (e.g. jlac10 for JP) —
otherwise the code/system pairing is incoherent. Currently dead in production (both
locale/us/code_mapping_lab.yaml and locale/jp/code_mapping_lab.yaml have full coverage
for every lab_name in use), but must not silently mistag a code if that ever changes.
Sibling regression to tests/unit/test_microbiology.py's
test_jp_unmapped_specimen_falls_back_to_test_loinc (TODO.md, 2026-07-04).
"""

from datetime import datetime

import pytest

from clinosim.codes import get_system_uri
from clinosim.modules.output._fhir_common import BundleContext
from clinosim.modules.output._fhir_observations import _bb_labs
from clinosim.types.encounter import Order, OrderResult, OrderStatus, OrderType

pytestmark = pytest.mark.unit


def _make_lab_order(order_id, lab_name, order_code, value, t):
    o = Order(
        order_id=order_id,
        encounter_id="enc1",
        patient_id="pt1",
        order_type=OrderType.LAB,
        order_code=order_code,
        display_name=lab_name,
        ordered_datetime=t,
        ordered_by="doc1",
        status=OrderStatus.RESULTED,
        panel_key="",
    )
    o.result = OrderResult(
        result_datetime=t,
        performed_by="tech1",
        lab_name=lab_name,
        value=value,
        unit="mg/dL",
    )
    return o


def _make_ctx(orders, country):
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
        primary_enc_id="enc1",
        patient_sex="",
    )


def test_jp_mapped_lab_uses_jlac10():
    """Sanity: a lab_name present in code_mapping_lab.yaml still resolves to jlac10 for JP."""
    t = datetime(2026, 7, 4, 8, 0)
    o = _make_lab_order("O1", "WBC", "6690-2", 6.0, t)
    ctx = _make_ctx([o], "JP")
    obs = _bb_labs(ctx)
    coding = obs[0]["code"]["coding"][0]
    assert coding["system"] == get_system_uri("jlac10")
    assert coding["code"] == "2A010"


def test_jp_unmapped_lab_falls_back_to_loinc_system():
    """An unmapped lab_name's LOINC-shaped order_code fallback must be tagged loinc,
    not jlac10 — the code system must co-vary with which branch produced the value."""
    t = datetime(2026, 7, 4, 8, 0)
    o = _make_lab_order("O1", "NotARealLabName", "99999-9", 1.0, t)
    ctx = _make_ctx([o], "JP")
    obs = _bb_labs(ctx)
    coding = obs[0]["code"]["coding"][0]
    assert coding["system"] == get_system_uri("loinc")
    assert coding["code"] == "99999-9"


def test_us_unmapped_lab_still_loinc():
    """US has no jlac10 involved at all — unaffected by this fix, still loinc throughout."""
    t = datetime(2026, 7, 4, 8, 0)
    o = _make_lab_order("O1", "NotARealLabName", "99999-9", 1.0, t)
    ctx = _make_ctx([o], "US")
    obs = _bb_labs(ctx)
    coding = obs[0]["code"]["coding"][0]
    assert coding["system"] == get_system_uri("loinc")
    assert coding["code"] == "99999-9"
