"""Issue #349 Phase 1b: antibiotic MedicationRequest opaque id + identifier round-trip.

Pins the FHIR-emission behavior introduced by Phase 1b:

* Antibiotic MR (``Order.order_id`` starts with ``ABX_ORDER_ID_PREFIX``
  = ``"req-abx-"``) has an opaque ``.id`` shaped ``mr-{12 hex}``.
* The original compound structural key is preserved in ``identifier[]``
  under the ``MEDICATION_REQUEST_KEY_SYSTEM`` URI for round-trip.
* Non-antibiotic MRs are unchanged (Phase 3 sibling-sweep will extend the
  pattern to other resource kinds).
* Antibiotic ``MedicationAdministration.request.reference`` resolves via
  the same :func:`_resolve_antibiotic_mr_id` derivation so cross-resource
  reference-integrity is preserved.
* JP-antibiotic MR carries all three identifier slices simultaneously:
  the Phase 1b structural key + the session-49 JP Core ``rpNumber`` +
  ``orderInRp``.
* The audit-side helper ``_medication_request_structural_key`` recovers
  the compound key from ``identifier[]`` and returns ``""`` for
  non-antibiotic rows so the narrow-rate gate's ``continue`` branch fires
  naturally instead of silently including them.
"""

from __future__ import annotations

import re
from typing import Any

import pytest

from clinosim.modules.antibiotic.engine import ABX_ORDER_ID_PREFIX
from clinosim.modules.output._fhir_medications import (
    MEDICATION_REQUEST_KEY_SYSTEM,
    _build_medication_admin,
    _build_medication_request,
    _resolve_antibiotic_mr_id,
)

pytestmark = pytest.mark.unit


_ANTIBIOTIC_ORDER_ID = "req-abx-hai-ENC-POP-000905-266868769799-vap-0-cft"
_ANTIBIOTIC_ORDER_ID_NARROWED = "req-abx-hai-ENC-POP-000905-266868769799-vap-0-cft-n"
_NON_ANTIBIOTIC_ORDER_ID = "ORD-ENC-POP-000905-266868769799-42"

_OPAQUE_MR_ID_PATTERN = re.compile(r"^mr-[0-9a-f]{12}$")


def _abx_order(order_id: str = _ANTIBIOTIC_ORDER_ID) -> dict[str, Any]:
    return {
        "order_id": order_id,
        "display_name": "Ceftriaxone 1g IV q24h",
        "order_type": "medication",
        "order_code": "",
        "ordered_datetime": "2026-06-15T08:00:00",
        "clinical_intent": "antibiotic:empirical vap",
    }


def _non_abx_order() -> dict[str, Any]:
    return {
        "order_id": _NON_ANTIBIOTIC_ORDER_ID,
        "display_name": "Aspirin 81mg PO daily",
        "order_type": "medication",
        "order_code": "",
        "ordered_datetime": "2026-06-15T08:00:00",
        "clinical_intent": "home medication",
    }


# === _resolve_antibiotic_mr_id ===


def test_resolve_antibiotic_mr_id_returns_opaque_for_antibiotic_prefix() -> None:
    mr_id = _resolve_antibiotic_mr_id(_ANTIBIOTIC_ORDER_ID)
    assert _OPAQUE_MR_ID_PATTERN.match(mr_id), f"expected mr-{{12 hex}}, got {mr_id!r}"


def test_resolve_antibiotic_mr_id_returns_input_for_non_antibiotic() -> None:
    """Phase 3 sibling-sweep will extend the opaque pattern; until then
    non-antibiotic order ids pass through unchanged so byte-diff is
    confined to antibiotic MRs."""
    assert _resolve_antibiotic_mr_id(_NON_ANTIBIOTIC_ORDER_ID) == _NON_ANTIBIOTIC_ORDER_ID


def test_resolve_antibiotic_mr_id_is_deterministic() -> None:
    """Cross-resource reference-integrity depends on same-input → same-output.
    MAR.request.reference and MR.id must resolve to the same opaque value
    from the same structural key."""
    a = _resolve_antibiotic_mr_id(_ANTIBIOTIC_ORDER_ID)
    b = _resolve_antibiotic_mr_id(_ANTIBIOTIC_ORDER_ID)
    assert a == b


def test_resolve_antibiotic_mr_id_distinguishes_empirical_vs_narrowed() -> None:
    """Empirical and narrowed regimens differ by the ``-n`` suffix in the
    structural key; their opaque ids must therefore differ so downstream
    consumers can tell them apart."""
    empirical = _resolve_antibiotic_mr_id(_ANTIBIOTIC_ORDER_ID)
    narrowed = _resolve_antibiotic_mr_id(_ANTIBIOTIC_ORDER_ID_NARROWED)
    assert empirical != narrowed


def test_resolve_antibiotic_mr_id_output_stays_well_under_fhir_limit() -> None:
    """The failure Issue #349 exists to eliminate: FHIR R4's 64-char
    Resource.id limit as a semantic constraint. Even with the longest
    realistic antibiotic structural key the opaque id is 15 chars."""
    result = _resolve_antibiotic_mr_id(_ANTIBIOTIC_ORDER_ID_NARROWED)
    assert len(result) == 15  # "mr-" (3) + 12 hex
    assert len(result) < 64


# === _build_medication_request (antibiotic path) ===


def test_antibiotic_mr_id_is_opaque_us() -> None:
    mr = _build_medication_request(_abx_order(), patient_id="pt1", country="US")
    assert _OPAQUE_MR_ID_PATTERN.match(mr["id"]), f"antibiotic MR.id should be opaque, got {mr['id']!r}"
    assert not mr["id"].startswith(ABX_ORDER_ID_PREFIX)


def test_antibiotic_mr_id_is_opaque_jp() -> None:
    mr = _build_medication_request(_abx_order(), patient_id="pt1", country="JP")
    assert _OPAQUE_MR_ID_PATTERN.match(mr["id"])


def test_antibiotic_mr_identifier_round_trip_us() -> None:
    """US antibiotic MR identifier[] contains ONLY the structural-key round-trip
    (US doesn't get JP Core rpNumber / orderInRp slices)."""
    mr = _build_medication_request(_abx_order(), patient_id="pt1", country="US")
    idents = mr["identifier"]
    assert len(idents) == 1
    assert idents[0] == {
        "system": MEDICATION_REQUEST_KEY_SYSTEM,
        "value": _ANTIBIOTIC_ORDER_ID,
    }


def test_antibiotic_mr_identifier_round_trip_jp_has_all_three_slices() -> None:
    """JP antibiotic MR carries all three identifier slices simultaneously —
    Phase 1b structural key + session-49 JP Core rpNumber + orderInRp.
    The Phase 1b entry is prepended so the JP Core slices retain their
    original order."""
    mr = _build_medication_request(
        _abx_order(),
        patient_id="pt1",
        country="JP",
        rp_number="1",
        order_in_rp="2",
    )
    idents = mr["identifier"]
    assert len(idents) == 3
    systems = [i["system"] for i in idents]
    assert systems == [
        MEDICATION_REQUEST_KEY_SYSTEM,
        "http://jpfhir.jp/fhir/core/mhlw/IdSystem/Medication-RPGroupNumber",
        "http://jpfhir.jp/fhir/core/mhlw/IdSystem/MedicationAdministrationIndex",
    ]
    # Structural key preserved verbatim
    assert idents[0]["value"] == _ANTIBIOTIC_ORDER_ID
    # JP Core slice values propagate from caller args
    assert idents[1]["value"] == "1"
    assert idents[2]["value"] == "2"


# === _build_medication_request (non-antibiotic path — unchanged) ===


def test_non_antibiotic_mr_id_unchanged_us() -> None:
    """Non-antibiotic MRs stay on the compound-id-as-key convention until
    Phase 3 sibling-sweep. Confining byte-diff to antibiotic MRs keeps the
    Phase 1b PR scope tight."""
    mr = _build_medication_request(_non_abx_order(), patient_id="pt1", country="US")
    assert mr["id"] == _NON_ANTIBIOTIC_ORDER_ID


def test_non_antibiotic_mr_has_no_structural_key_identifier_us() -> None:
    """Only antibiotic MRs get the Phase 1b structural-key round-trip; US
    non-antibiotic MRs have no identifier[] at all (JP still gets the JP
    Core slices)."""
    mr = _build_medication_request(_non_abx_order(), patient_id="pt1", country="US")
    assert "identifier" not in mr


def test_non_antibiotic_mr_jp_has_only_jp_core_slices() -> None:
    mr = _build_medication_request(_non_abx_order(), patient_id="pt1", country="JP")
    idents = mr["identifier"]
    systems = [i["system"] for i in idents]
    assert MEDICATION_REQUEST_KEY_SYSTEM not in systems
    assert "http://jpfhir.jp/fhir/core/mhlw/IdSystem/Medication-RPGroupNumber" in systems
    assert "http://jpfhir.jp/fhir/core/mhlw/IdSystem/MedicationAdministrationIndex" in systems


# === MAR.request.reference cross-resource integrity ===


def _abx_mar(order_id: str = _ANTIBIOTIC_ORDER_ID) -> dict[str, Any]:
    return {
        "order_id": order_id,
        "drug_name": "Ceftriaxone 1g IV q24h",
        "dose": "1g",
        "administered_datetime": "2026-06-15T08:00:00",
        "status": "completed",
    }


def _non_abx_mar() -> dict[str, Any]:
    return {
        "order_id": _NON_ANTIBIOTIC_ORDER_ID,
        "drug_name": "Aspirin 81mg PO daily",
        "dose": "81mg",
        "administered_datetime": "2026-06-15T08:00:00",
        "status": "completed",
    }


def test_antibiotic_mar_request_reference_uses_opaque_mr_id() -> None:
    """Reference-integrity invariant: MAR.request.reference must equal
    ``MedicationRequest/{opaque_id}`` where ``opaque_id`` is the value
    :func:`_build_medication_request` sets on the parent MR."""
    mar = _build_medication_admin(_abx_mar(), patient_id="pt1", index=0, country="US")
    mr = _build_medication_request(_abx_order(), patient_id="pt1", country="US")
    assert mar["request"]["reference"] == f"MedicationRequest/{mr['id']}"


def test_non_antibiotic_mar_request_reference_unchanged() -> None:
    """Non-antibiotic MAR reference stays on the compound-key convention
    (mirrors the non-antibiotic MR.id staying unchanged in Phase 1b)."""
    mar = _build_medication_admin(_non_abx_mar(), patient_id="pt1", index=0, country="US")
    assert mar["request"]["reference"] == f"MedicationRequest/{_NON_ANTIBIOTIC_ORDER_ID}"


# === Audit gate: _medication_request_structural_key ===


def test_audit_gate_recovers_structural_key_from_antibiotic_mr() -> None:
    """The narrow-rate gate reads the compound key from identifier[] instead
    of the (opaque) id, so ``ABX_ORDER_ID_PREFIX in key`` and
    ``key.endswith(ABX_NARROW_SUFFIX)`` continue to work exactly as before
    Phase 1b — just sourced from identifier[] rather than the id string."""
    from clinosim.audit.axes.clinical import _medication_request_structural_key

    mr = _build_medication_request(_abx_order(), patient_id="pt1", country="US")
    assert _medication_request_structural_key(mr) == _ANTIBIOTIC_ORDER_ID


def test_audit_gate_returns_empty_for_non_antibiotic_mr() -> None:
    """Non-antibiotic MRs have no structural-key identifier (until Phase 3
    sweep). The helper returns ``""`` so the caller's
    ``ABX_ORDER_ID_PREFIX in structural_key`` check naturally excludes
    them via ``continue`` — same shape as the pre-Phase-1b gate."""
    from clinosim.audit.axes.clinical import _medication_request_structural_key

    mr = _build_medication_request(_non_abx_order(), patient_id="pt1", country="US")
    assert _medication_request_structural_key(mr) == ""


def test_audit_gate_returns_empty_for_missing_identifier_list() -> None:
    """Defensive: rows without ``identifier`` (legacy resources, non-MR
    resources accidentally passed through) must return ``""`` rather than
    raise, so the gate skips them cleanly."""
    from clinosim.audit.axes.clinical import _medication_request_structural_key

    assert _medication_request_structural_key({}) == ""
    assert _medication_request_structural_key({"identifier": None}) == ""
    assert _medication_request_structural_key({"identifier": []}) == ""


def test_audit_gate_recognizes_narrowed_regimen_from_identifier() -> None:
    """The ``-n`` narrowed-suffix check still fires when reading the
    structural key from identifier[] instead of the (now opaque) id."""
    from clinosim.audit.axes.clinical import _medication_request_structural_key

    narrowed_order = _abx_order(_ANTIBIOTIC_ORDER_ID_NARROWED)
    mr = _build_medication_request(narrowed_order, patient_id="pt1", country="US")
    key = _medication_request_structural_key(mr)
    assert key.endswith("-n")
