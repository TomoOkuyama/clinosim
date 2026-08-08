"""Issue #436: FHIR emit shape for STOP (discontinuation) MedicationRequest.

Pins the behavior introduced by session 81's F1' + F3 combined fix:

- F1' (id-based emit-time override): when an ``Order.order_id`` contains
  ``MED_STOP_ORDER_ID_MARKER`` (= ``"-STOP-"``), the emitted
  ``MedicationRequest.status`` MUST be ``"stopped"`` regardless of the
  underlying ``OrderStatus`` mapping. This lets FHIR consumers tell a
  discontinuation apart from an active prescription without reverse-
  engineering the id naming convention.

- F3 (clinical_intent → note[].text): the STOP order's
  ``clinical_intent`` (e.g. ``"Day 2 sudden_deterioration: stop
  Warfarin"``) is copied into ``note[].text`` so human readers see the
  rationale. Regular orders MUST NOT get a ``note`` from this path.

Regression coverage: regular (non-STOP) MedicationRequests MUST NOT be
affected — this fix is scoped to the STOP-id branch only.

Rationale for the emit-layer approach (not Order-layer):
session 79 verified that reassigning ``OrderStatus.STOPPED`` at Order
creation shifts ``_generate_mar``'s per-order rng cursor and produces a
+6 ServiceRequest / +7 Specimen / +1 DiagnosticReport cascade (AD-16
determinism violation). The id-based emit override is rng-neutral.
"""

from __future__ import annotations

from typing import Any

import pytest

from clinosim.modules._shared import MED_STOP_ORDER_ID_MARKER
from clinosim.modules.output.fhir_r4.medications.medications import _build_medication_request

pytestmark = pytest.mark.unit


_STOP_ORDER_ID = "ORD-ENC-POP-002104-424255862466-STOP-D2-4-Warfarin"
_STOP_CLINICAL_INTENT = "Day 2 sudden_deterioration: stop Warfarin"
_REGULAR_ORDER_ID = "ORD-ENC-POP-002104-424255862466-42"


def _stop_order(order_id: str = _STOP_ORDER_ID) -> dict[str, Any]:
    return {
        "order_id": order_id,
        "display_name": "DISCONTINUE: Warfarin",
        "order_type": "medication",
        "order_code": "3332001",
        "ordered_datetime": "2026-06-17T10:00:00",
        "encounter_id": "ENC-POP-002104-424255862466",
        "status": "placed",
        "clinical_intent": _STOP_CLINICAL_INTENT,
    }


def _regular_order(order_id: str = _REGULAR_ORDER_ID) -> dict[str, Any]:
    return {
        "order_id": order_id,
        "display_name": "Aspirin 81mg PO daily",
        "order_type": "medication",
        "order_code": "",
        "ordered_datetime": "2026-06-15T08:00:00",
        "encounter_id": "ENC-POP-002104-424255862466",
        "status": "placed",
        "clinical_intent": "home medication",
    }


# ────────────────────────────────────────────────────────────────────
# F1': status = "stopped" for STOP orders


def test_stop_order_emits_status_stopped() -> None:
    """MedicationRequest.status MUST be 'stopped' when the order id
    contains the STOP marker, regardless of the underlying OrderStatus."""
    mr = _build_medication_request(
        _stop_order(),
        patient_id="p1",
        country="JP",
        encounter_id="ENC-POP-002104-424255862466",
        encounter_type="inpatient",
    )
    assert mr["status"] == "stopped", f"expected status='stopped' for STOP order, got {mr['status']!r}"


def test_regular_order_status_unchanged() -> None:
    """Regular orders MUST NOT be affected — the fix is STOP-scoped only.

    A ``home medication`` order on ``status='placed'`` maps to ``active``
    via ``_map_order_status_to_fhir``; the completion-check branch does
    NOT fire (not episodic, not outpatient); expect status='active'."""
    mr = _build_medication_request(
        _regular_order(),
        patient_id="p1",
        country="JP",
        encounter_id="ENC-POP-002104-424255862466",
        encounter_type="inpatient",
    )
    assert mr["status"] == "active", f"regular MR must stay 'active', got {mr['status']!r}"


def test_stop_marker_constant_is_shared() -> None:
    """The marker constant is the single source of truth for both the
    Order-id writer (``inpatient.py``) and this FHIR reader. Pinning it
    here catches a rename that would otherwise silently break emission."""
    assert MED_STOP_ORDER_ID_MARKER == "-STOP-"
    assert MED_STOP_ORDER_ID_MARKER in _STOP_ORDER_ID


# ────────────────────────────────────────────────────────────────────
# F3: clinical_intent → note[].text


def test_stop_order_emits_clinical_intent_as_note() -> None:
    mr = _build_medication_request(
        _stop_order(),
        patient_id="p1",
        country="JP",
        encounter_id="ENC-POP-002104-424255862466",
        encounter_type="inpatient",
    )
    assert mr.get("note") == [{"text": _STOP_CLINICAL_INTENT}], (
        f"expected note[].text = clinical_intent for STOP order, got {mr.get('note')!r}"
    )


def test_stop_order_without_clinical_intent_omits_note() -> None:
    """No clinical_intent → no note[] emission (avoid empty text)."""
    order = _stop_order()
    order["clinical_intent"] = ""
    mr = _build_medication_request(
        order,
        patient_id="p1",
        country="JP",
        encounter_id="ENC-POP-002104-424255862466",
        encounter_type="inpatient",
    )
    assert "note" not in mr, f"empty clinical_intent must not emit note, got {mr.get('note')!r}"
    # Status override still fires — F1' does not depend on clinical_intent presence.
    assert mr["status"] == "stopped"


def test_regular_order_does_not_get_stop_note() -> None:
    """Regular MRs MUST NOT get a note[] from the STOP path. The note[]
    field addition is scoped to STOP orders only."""
    mr = _build_medication_request(
        _regular_order(),
        patient_id="p1",
        country="JP",
        encounter_id="ENC-POP-002104-424255862466",
        encounter_type="inpatient",
    )
    assert "note" not in mr, f"regular MR must not emit note from the STOP-order branch, got {mr.get('note')!r}"


# ────────────────────────────────────────────────────────────────────
# Marker positional independence


def test_stop_detection_matches_marker_anywhere_in_id() -> None:
    """The marker is a substring check — id shape variations (e.g.
    trailing suffix) MUST still trigger the override. Pins the shared-
    marker convention documented in ``clinosim/modules/_shared.py``."""
    variant_id = f"ORD-ENC-P{MED_STOP_ORDER_ID_MARKER}D7-0-Aspirin-extra"
    order = _stop_order(variant_id)
    mr = _build_medication_request(
        order,
        patient_id="p1",
        country="JP",
        encounter_id="ENC-P",
        encounter_type="inpatient",
    )
    assert mr["status"] == "stopped"
    assert mr.get("note") == [{"text": _STOP_CLINICAL_INTENT}]
