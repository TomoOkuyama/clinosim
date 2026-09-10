"""Issue #1217: MedicationAdministration.request gates on the post-dedup MR set.

`_bb_medication_requests` runs `_dedup_medication_requests` (Issue #1177,
byte-identical) and `_dedup_same_class_orders` (Issues #1176 / #1179,
same-day same-class) on its output before returning. The pre-fix
`_bb_medication_admins` gate built `_mr_ids` from the raw
`ctx.record["orders"]` list — orders that WERE emitted as MRs and then
dropped by dedup still appeared in `_mr_ids`, so
`MedicationAdministration.request.reference` pointing at them passed the
gate and shipped dangling.

P=10000 s=1111 audit: 357 dangling MA→MR references (insulin sliding-
scale / enoxaparin standing-order / prednisolone course — MA emitted
per-day but MR dedup coalesces the underlying orders into one MR).

Fix: `_build_bundle` populates `BundleContext.emitted_mr_ids` right
before `_bb_medication_admins` runs, from the entries already emitted
by earlier builders. The MA builder gates on that set instead of the
raw order set — references to dropped MRs are popped (existing pop()
semantic; the dedup helpers keep the byte-identical or first-of-class
MR, and the MA's clinical fact is preserved by the record's
authoritative dose/route/effectiveDateTime on the MA itself).
"""

from __future__ import annotations

from typing import Any

import pytest

from clinosim.modules.output.fhir_r4.lib.common import BundleContext
from clinosim.modules.output.fhir_r4.lib.inline_bb import _bb_medication_admins

pytestmark = pytest.mark.unit


def _mk_ctx(
    orders: list[dict[str, Any]],
    mars: list[dict[str, Any]],
    emitted_mr_ids: set[str] | None = None,
) -> BundleContext:
    record = {
        "patient": {"patient_id": "POP-000001", "sex": "F"},
        "encounters": [
            {
                "encounter_id": "ENC-POP-000001-abc",
                "encounter_type": "inpatient",
                "status": "finished",
                "admission_datetime": "2026-03-01T08:00:00",
                "discharge_datetime": "2026-03-10T12:00:00",
            }
        ],
        "clinical_diagnosis": {"admission_diagnosis_code": "E11.9", "discharge_diagnosis_code": "E11.9"},
        "orders": orders,
        "medication_administrations": mars,
    }
    return BundleContext(
        record=record,
        country="JP",
        roster_map={},
        hospital_config={},
        patient_data=record["patient"],
        patient_id="POP-000001",
        is_readmission=False,
        prior_encounter_id=None,
        primary_dx_code="E11.9",
        admit_dx_code="E11.9",
        admit_dx_system="icd-10-cm",
        primary_enc_id="ENC-POP-000001-abc",
        patient_sex="F",
        emitted_mr_ids=emitted_mr_ids,
    )


def _mk_order(order_id: str, drug: str = "Insulin regular") -> dict[str, Any]:
    return {
        "order_id": order_id,
        "order_type": "medication",
        "display_name": drug,
        "ordered_by": "DR-001",
        "encounter_id": "ENC-POP-000001-abc",
        "ordered_datetime": "2026-03-01T08:00:00",
    }


def _mk_mar(order_id: str, drug: str = "Insulin regular", ts: str = "2026-03-01T08:00:00") -> dict[str, Any]:
    return {
        "order_id": order_id,
        "drug_name": drug,
        "scheduled_datetime": ts,
        "actual_datetime": ts,
        "status": "given",
        "dose": "10 units",
    }


def test_ma_request_survives_when_mr_id_in_emitted_set() -> None:
    """Regression guard: MA whose MR id is in `emitted_mr_ids` keeps its request."""
    from clinosim.modules.output.fhir_r4.medications.medications import _resolve_mr_id

    order = _mk_order("ord-1")
    mr_id = _resolve_mr_id("ord-1")
    ctx = _mk_ctx([order], [_mk_mar("ord-1")], emitted_mr_ids={mr_id})
    mas = _bb_medication_admins(ctx)
    assert len(mas) == 1
    assert "request" in mas[0]
    assert mas[0]["request"]["reference"] == f"MedicationRequest/{mr_id}"


def test_ma_request_dropped_when_mr_id_dedup_removed() -> None:
    """Core fix: MA whose MR id is NOT in the post-dedup set gets its request popped."""
    order = _mk_order("ord-1")
    ctx = _mk_ctx([order], [_mk_mar("ord-1")], emitted_mr_ids=set())  # empty = all MRs deduped
    mas = _bb_medication_admins(ctx)
    assert len(mas) == 1
    assert "request" not in mas[0]


def test_ma_request_fallback_to_order_gate_when_emitted_set_none() -> None:
    """When `emitted_mr_ids` is None (unit-test isolation), fall back to the pre-#1217
    order-set gate. Preserves the pre-fix behaviour for callers that don't run the
    pre-MA index pass."""
    order = _mk_order("ord-1")
    ctx = _mk_ctx([order], [_mk_mar("ord-1")], emitted_mr_ids=None)
    mas = _bb_medication_admins(ctx)
    assert len(mas) == 1
    # The order is in ctx.record.orders, so the pre-#1217 gate lets the ref through.
    assert "request" in mas[0]


def test_ma_request_gate_survives_multiple_mars_for_one_mr() -> None:
    """Standing-order pattern: 3 MAs for one MR (insulin BID over 3 days).
    All three keep their request when the MR id is in emitted_mr_ids."""
    from clinosim.modules.output.fhir_r4.medications.medications import _resolve_mr_id

    order = _mk_order("ord-insulin")
    mr_id = _resolve_mr_id("ord-insulin")
    mars = [_mk_mar("ord-insulin", ts=f"2026-03-{d:02d}T08:00:00") for d in (1, 2, 3)]
    ctx = _mk_ctx([order], mars, emitted_mr_ids={mr_id})
    mas = _bb_medication_admins(ctx)
    assert len(mas) == 3
    for ma in mas:
        assert ma["request"]["reference"] == f"MedicationRequest/{mr_id}"


def test_ma_request_gate_drops_all_refs_when_mr_deduped_away() -> None:
    """Standing-order pattern where the MR was deduped: all MA refs must be popped."""
    order = _mk_order("ord-insulin")
    mars = [_mk_mar("ord-insulin", ts=f"2026-03-{d:02d}T08:00:00") for d in (1, 2, 3)]
    ctx = _mk_ctx([order], mars, emitted_mr_ids=set())
    mas = _bb_medication_admins(ctx)
    assert len(mas) == 3
    for ma in mas:
        assert "request" not in ma
