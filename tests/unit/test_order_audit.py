"""Unit tests for order ServiceRequest audit module (PR1 — AD-60 plug-in #3).

The module-level import fires the side-effect that registers ModuleAuditSpec.
Tests call discover() to ensure the spec is loaded even after _reset_for_test()
clears the registry (same pattern as tests/integration/test_antibiotic_audit.py).
"""
from __future__ import annotations

import pytest

from clinosim.audit.registry import discover, get_registered


@pytest.mark.unit
def test_order_audit_module_registered():
    """discover() finds and registers ModuleAuditSpec 'order_service_request'."""
    discover()
    specs = get_registered()
    assert "order_service_request" in specs, (
        f"'order_service_request' not in registry after discover(); "
        f"registered: {sorted(specs)}"
    )


@pytest.mark.unit
def test_lift_firing_proof_is_callable():
    """lift_firing_proof must be a zero-arg callable (not a dict)."""
    discover()
    spec = get_registered()["order_service_request"]
    assert spec.lift_firing_proof is not None
    assert callable(spec.lift_firing_proof), (
        "lift_firing_proof must be a callable (zero-arg factory returning "
        "dict with equality_checks); storing a raw dict bypasses the "
        "silent_no_op axis and is the PR-90 class bug in the audit framework"
    )


@pytest.mark.unit
def test_lift_firing_proof_has_required_equality_checks():
    """The lift_firing_proof factory must return >= 7 equality_checks tuples."""
    discover()
    spec = get_registered()["order_service_request"]
    assert spec.lift_firing_proof is not None
    proof = spec.lift_firing_proof()
    assert "equality_checks" in proof, (
        "proof must contain 'equality_checks' key; "
        f"got keys: {sorted(proof.keys())}"
    )
    checks = proof["equality_checks"]
    assert len(checks) >= 7, (
        f"Expected >= 7 equality_checks, got {len(checks)}: {checks}"
    )
    # All checks must be (label, actual, expected) 3-tuples
    for i, check in enumerate(checks):
        assert len(check) == 3, (
            f"equality_checks[{i}] must be (label, actual, expected), got: {check!r}"
        )

    # Verify the 7 canonical substrings appear in the labels
    labels_text = " ".join(label for label, _, _ in checks)
    expected_substrings = [
        "PLACER_ORDER_NUMBER_SYSTEM",
        "108252007",
        "LAB",
        "ServiceRequest count > 0 when lab Order count > 0",
        "panel SR count > 0",
        "every panel SR id is well-formed",
        "SR id schemes are disjoint",
    ]
    for substring in expected_substrings:
        assert substring in labels_text, (
            f"Missing equality_check label substring: {substring!r}\n"
            f"All labels: {labels_text}"
        )


@pytest.mark.unit
def test_lift_firing_proof_all_checks_pass():
    """All equality_checks must have actual == expected (no canonical drift)."""
    discover()
    spec = get_registered()["order_service_request"]
    proof = spec.lift_firing_proof()
    failures = [
        (label, actual, expected)
        for label, actual, expected in proof["equality_checks"]
        if actual != expected
    ]
    assert not failures, (
        "Some equality_checks failed (canonical drift detected):\n"
        + "\n".join(
            f"  {label!r}: actual={actual!r} != expected={expected!r}"
            for label, actual, expected in failures
        )
    )
