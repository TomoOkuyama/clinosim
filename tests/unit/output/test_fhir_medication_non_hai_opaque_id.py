"""Issue #853: opaque MR.id + identifier round-trip extended to all MR paths.

Sibling of tests/unit/output/test_fhir_medication_opaque_id.py (antibiotic-only,
PR #357) — this file pins the widened contract for non-HAI inpatient orders,
discharge-Rx (rxdc-), and outpatient-Rx (rxopd-) plus their MedicationAdministration
cross-references.
"""

from __future__ import annotations

import re

import pytest

from clinosim.modules.output.fhir_r4.medications.medications import (
    _resolve_mr_id,
)

pytestmark = pytest.mark.unit

_OPAQUE_MR_ID_PATTERN = re.compile(r"^mr-[0-9a-f]{12}$")

_NON_ANTIBIOTIC_ORDER_ID = "ORD-ENC-POP-000012-351553611449-ESC-D3-Aminophy"
_INPATIENT_HM_ORDER_ID = "ORD-ENC-POP-002408-089914154887-HM-00"
_ADMISSION_ORDER_ID = "ORD-ENC-POP-002408-089914154887-ADM-S02"


def test_resolve_mr_id_returns_opaque_for_non_antibiotic_order() -> None:
    """Widened contract (Issue #853): every non-empty order_id -> opaque `mr-` id."""
    result = _resolve_mr_id(_NON_ANTIBIOTIC_ORDER_ID)
    assert _OPAQUE_MR_ID_PATTERN.match(result), f"got {result!r}"


def test_resolve_mr_id_is_deterministic() -> None:
    """Same order_id must always resolve to the same opaque id (byte-diff invariant)."""
    a = _resolve_mr_id(_NON_ANTIBIOTIC_ORDER_ID)
    b = _resolve_mr_id(_NON_ANTIBIOTIC_ORDER_ID)
    assert a == b


def test_resolve_mr_id_differs_across_orders() -> None:
    """Distinct order_ids yield distinct opaque ids (collision-avoidance smoke)."""
    a = _resolve_mr_id(_NON_ANTIBIOTIC_ORDER_ID)
    b = _resolve_mr_id(_INPATIENT_HM_ORDER_ID)
    c = _resolve_mr_id(_ADMISSION_ORDER_ID)
    assert a != b
    assert b != c
    assert a != c


def test_resolve_mr_id_still_opaque_for_antibiotic_prefix() -> None:
    """Backwards-compat: existing antibiotic prefix still gets opaque id.

    Pre-fix `_resolve_antibiotic_mr_id` returned opaque for `req-abx-` and
    passthrough for everything else. Widened `_resolve_mr_id` returns opaque
    for everything, so antibiotic behaviour is unchanged.
    """
    result = _resolve_mr_id("req-abx-hai-ENC-POP-000905-266868769799-vap-0-cft")
    assert _OPAQUE_MR_ID_PATTERN.match(result)


# === _build_medication_request (non-HAI full-emit path) ===

from clinosim.modules.output.fhir_r4.medications.medications import (  # noqa: E402
    MEDICATION_REQUEST_KEY_SYSTEM,
    _build_medication_request,
)


def _non_hai_order(order_id: str = _NON_ANTIBIOTIC_ORDER_ID) -> dict:
    """Minimal Order fixture that exercises the non-HAI MR emit path."""
    return {
        "order_id": order_id,
        "display_name": "Aminophylline 250mg IV q6h",
        "order_type": "medication",
        "order_code": "",
        "ordered_datetime": "2026-02-14T10:00:00",
        "clinical_intent": "Escalation day 3: Aminophylline (no improvement)",
    }


def test_non_hai_mr_id_is_opaque_us() -> None:
    """The full MR emit path (not just the resolver) produces the opaque id."""
    mr = _build_medication_request(_non_hai_order(), patient_id="pt1", country="US")
    assert _OPAQUE_MR_ID_PATTERN.match(mr["id"]), f"got {mr['id']!r}"


def test_non_hai_mr_id_is_opaque_jp() -> None:
    mr = _build_medication_request(_non_hai_order(), patient_id="pt1", country="JP")
    assert _OPAQUE_MR_ID_PATTERN.match(mr["id"]), f"got {mr['id']!r}"


def test_non_hai_mr_us_carries_structural_key_identifier() -> None:
    """Post-Issue-#853: even US non-HAI MR gets the structural-key round-trip."""
    mr = _build_medication_request(_non_hai_order(), patient_id="pt1", country="US")
    idents = mr.get("identifier") or []
    structural = [i for i in idents if i.get("system") == MEDICATION_REQUEST_KEY_SYSTEM]
    assert len(structural) == 1, f"expected 1 structural-key ident, got {structural!r}"
    assert structural[0]["value"] == _NON_ANTIBIOTIC_ORDER_ID


def test_non_hai_mr_jp_carries_structural_key_alongside_jp_core_slices() -> None:
    """JP non-HAI MR: structural-key + rpNumber + orderInRp all coexist."""
    mr = _build_medication_request(_non_hai_order(), patient_id="pt1", country="JP")
    systems = [i.get("system") for i in mr.get("identifier") or []]
    assert MEDICATION_REQUEST_KEY_SYSTEM in systems
    assert "http://jpfhir.jp/fhir/core/mhlw/IdSystem/Medication-RPGroupNumber" in systems
    assert "http://jpfhir.jp/fhir/core/mhlw/IdSystem/MedicationAdministrationIndex" in systems


# === discharge-Rx / outpatient-Rx opaque id (Issue #853 Task 4) ===

from clinosim.modules.output.fhir_r4.medications.medications import (  # noqa: E402
    _resolve_dc_rx_id,
    _resolve_opd_rx_id,
)

_OPAQUE_DC_RX_PATTERN = re.compile(r"^rxdc-[0-9a-f]{12}$")
_OPAQUE_OPD_RX_PATTERN = re.compile(r"^rxopd-[0-9a-f]{12}$")


def test_resolve_dc_rx_id_returns_opaque() -> None:
    """Discharge-Rx opaque id: `rxdc-` (5 char) + 12-hex digest."""
    result = _resolve_dc_rx_id("ENC-POP-000058-281217974268-01")
    assert _OPAQUE_DC_RX_PATTERN.match(result), f"got {result!r}"


def test_resolve_opd_rx_id_returns_opaque() -> None:
    """Outpatient-Rx opaque id: `rxopd-` (6 char) + 12-hex digest."""
    result = _resolve_opd_rx_id("ENC-POP-000058-281217974268-01")
    assert _OPAQUE_OPD_RX_PATTERN.match(result), f"got {result!r}"


def test_dc_rx_and_opd_rx_ids_differ_for_same_structural_key() -> None:
    """The prefix distinguishes discharge-Rx from outpatient-Rx even for identical structural keys.

    Consumers rely on this distinction (Issue #445 intent).
    """
    a = _resolve_dc_rx_id("ENC-POP-000058-281217974268-01")
    b = _resolve_opd_rx_id("ENC-POP-000058-281217974268-01")
    assert a != b
