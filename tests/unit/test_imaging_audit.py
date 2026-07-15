"""Unit tests for imaging chain audit module (AD-60 plug-in #4, Tier 1 #2 PR1).

The discover() call fires the side-effect that registers ModuleAuditSpec.
Tests call discover() to ensure the spec is loaded even after _reset_for_test()
clears the registry (same pattern as test_order_audit.py).
"""

from __future__ import annotations

import pytest

from clinosim.audit.registry import discover, get_registered


@pytest.mark.unit
def test_imaging_audit_module_registered():
    """discover() finds and registers ModuleAuditSpec 'imaging_chain'."""
    discover()
    specs = get_registered()
    assert "imaging_chain" in specs, f"'imaging_chain' not in registry after discover(); registered: {sorted(specs)}"


@pytest.mark.unit
def test_lift_firing_proof_is_callable():
    """lift_firing_proof must be a zero-arg callable (not a raw dict).

    Storing a raw dict bypasses the silent_no_op axis execution and is
    itself the PR-90 class bug in the audit framework (the proof never runs).
    """
    discover()
    spec = get_registered()["imaging_chain"]
    assert spec.lift_firing_proof is not None
    assert callable(spec.lift_firing_proof), (
        "lift_firing_proof must be a callable (zero-arg factory returning "
        "dict with equality_checks); storing a raw dict bypasses the "
        "silent_no_op axis and is the PR-90 class bug in the audit framework"
    )


@pytest.mark.unit
def test_lift_firing_proof_has_15_equality_checks():
    """The lift_firing_proof factory must return >= 15 equality_checks 3-tuples."""
    discover()
    spec = get_registered()["imaging_chain"]
    assert spec.lift_firing_proof is not None
    proof = spec.lift_firing_proof()
    assert "equality_checks" in proof, f"proof must contain 'equality_checks' key; got keys: {sorted(proof.keys())}"
    checks = proof["equality_checks"]
    assert len(checks) >= 15, f"Expected >= 15 equality_checks, got {len(checks)}: {checks}"
    # All checks must be (label, actual, expected) 3-tuples.
    for i, check in enumerate(checks):
        assert len(check) == 3, f"equality_checks[{i}] must be (label, actual, expected), got: {check!r}"


@pytest.mark.unit
def test_canonical_constant_checks_present():
    """All 4 canonical constants must appear in equality_check labels.

    These are the silent-no-op defense Layer 1-2 checks that guard against
    constant drift (PR-90 class: UPPERCASE vs lowercase keys, etc.).
    """
    discover()
    spec = get_registered()["imaging_chain"]
    proof = spec.lift_firing_proof()
    checks = proof["equality_checks"]
    labels = " ".join(label for label, _, _ in checks)
    expected_substrings = [
        "IMAGING_CATEGORY_SNOMED",
        "IMAGING_CATEGORY_V2_0074",
        "DICOM_UID_SYSTEM",
        "DICOM_WADO_RS_CONNECTION_TYPE",
    ]
    for substring in expected_substrings:
        assert substring in labels, f"Missing canonical constant label substring: {substring!r}\nAll labels: {labels}"


@pytest.mark.unit
def test_no_drop_invariant_checks_present():
    """Section 3.4 emission matrix no-drop gates must appear in equality_checks.

    These guards verify that CIF fields (findings_text, impression_text,
    body_site, findings_codes) are faithfully mapped to FHIR targets without
    silent omission.
    """
    discover()
    spec = get_registered()["imaging_chain"]
    proof = spec.lift_firing_proof()
    checks = proof["equality_checks"]
    labels = " ".join(label for label, _, _ in checks)
    expected_substrings = [
        "findings_text",
        "impression_text",
        "body_site",
        "findings_codes",
    ]
    for substring in expected_substrings:
        assert substring in labels, f"Missing no-drop invariant label substring: {substring!r}\nAll labels: {labels}"


@pytest.mark.unit
def test_lift_firing_proof_all_checks_pass():
    """All 15 equality_checks must have actual == expected (no canonical drift)."""
    discover()
    spec = get_registered()["imaging_chain"]
    proof = spec.lift_firing_proof()
    failures = [(label, actual, expected) for label, actual, expected in proof["equality_checks"] if actual != expected]
    assert not failures, "Some equality_checks failed (canonical drift or builder silent-no-op):\n" + "\n".join(
        f"  {label!r}: actual={actual!r} != expected={expected!r}" for label, actual, expected in failures
    )
