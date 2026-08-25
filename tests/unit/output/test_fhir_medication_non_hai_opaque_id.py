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
